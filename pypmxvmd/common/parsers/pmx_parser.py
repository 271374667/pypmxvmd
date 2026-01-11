"""
PyPMXVMD PMX解析器

负责解析和写入PMX格式文件。
支持PMX 2.0和2.1格式的完整解析。
"""

import struct
from pathlib import Path
from typing import List, Optional, Union

from pypmxvmd.common.models.pmx import (
    PmxModel, PmxHeader, PmxVertex, PmxMaterial, WeightMode, SphMode, MaterialFlags
)
from pypmxvmd.common.io.binary_io import BinaryIOHandler

# 尝试导入Cython优化模块
try:
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython
    _CYTHON_AVAILABLE = True
except ImportError:
    _CYTHON_AVAILABLE = False


class PmxParser:
    """PMX文件解析器
    
    负责PMX文件的读取和写入操作。
    支持PMX 2.0和2.1格式的完整解析和验证。
    """
    
    def __init__(self):
        """初始化PMX解析器"""
        self._io_handler = BinaryIOHandler("utf-16le")  # PMX默认使用UTF-16LE
        self._use_utf8 = False  # 编码标志
        self._progress_callback = None
        
        # 索引类型格式字符串
        self._vertex_index_format = "B"  # 顶点索引格式
        self._texture_index_format = "b"  # 纹理索引格式
        self._material_index_format = "b"  # 材质索引格式
        self._bone_index_format = "b"    # 骨骼索引格式
        self._morph_index_format = "b"   # 变形索引格式
        self._rigidbody_index_format = "b"  # 刚体索引格式
        
    def set_progress_callback(self, callback) -> None:
        """设置进度回调函数
        
        Args:
            callback: 进度回调函数，接受(current, total)参数
        """
        self._progress_callback = callback
    
    def _report_progress(self, current: int, total: int) -> None:
        """报告解析进度"""
        if self._progress_callback:
            self._progress_callback(current, total)
    
    def parse_file(self, file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
        """解析PMX文件

        默认使用Cython优化解析，如果Cython模块不可用则回退到纯Python版本。

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        # 优先使用Cython解析
        if _CYTHON_AVAILABLE:
            return self.parse_file_cython(file_path, more_info)

        # 回退到纯Python快速解析
        return self._parse_file_python(file_path, more_info)

    def _parse_file_python(self, file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
        """纯Python解析PMX文件（原始实现）

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始解析PMX文件: {file_path}")

        # 读取文件数据
        data = self._io_handler.read_file(file_path)

        # 创建PMX模型对象
        pmx_model = PmxModel()

        try:
            # 解析文件头
            pmx_model.header = self._parse_header(data)

            # 根据头信息设置解析参数
            self._setup_parsing_parameters(data)

            # 解析各个数据段
            pmx_model.vertices = self._parse_vertices(data)
            pmx_model.faces = self._parse_faces(data)
            pmx_model.materials = self._parse_materials(data)

            # TODO: 解析其他数据段（骨骼、变形等）
            # pmx_model.bones = self._parse_bones(data)
            # pmx_model.morphs = self._parse_morphs(data)

            if more_info:
                print(f"PMX解析完成: {len(pmx_model.vertices)}个顶点, "
                      f"{len(pmx_model.faces)}个面, {len(pmx_model.materials)}个材质")

            return pmx_model

        except Exception as e:
            raise ValueError(f"PMX文件解析失败: {e}")

    def parse_file_fast(self, file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
        """快速解析PMX文件（性能优化版本）

        使用内部缓冲区和偏移量追踪，避免O(n)的切片删除操作。
        对于大型PMX文件，性能提升显著。

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始快速解析PMX文件: {file_path}")

        # 使用快速读取方法
        self._io_handler.read_file_fast(file_path)

        # 创建PMX模型对象
        pmx_model = PmxModel()

        try:
            # 解析文件头
            pmx_model.header = self._parse_header_fast()

            # 根据头信息设置解析参数（使用快速版本）
            self._setup_parsing_parameters_fast()

            # 解析各个数据段
            pmx_model.vertices = self._parse_vertices_fast(more_info)
            pmx_model.faces = self._parse_faces_fast(more_info)
            pmx_model.materials = self._parse_materials_fast(more_info)

            if more_info:
                print(f"PMX快速解析完成: {len(pmx_model.vertices)}个顶点, "
                      f"{len(pmx_model.faces)}个面, {len(pmx_model.materials)}个材质")

            return pmx_model

        except Exception as e:
            raise ValueError(f"PMX文件快速解析失败: {e}")

    def parse_file_cython(self, file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
        """使用Cython解析PMX文件（最高性能版本）

        需要编译Cython模块后才能使用。
        如果Cython模块不可用，将自动回退到parse_file_fast。

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        if not _CYTHON_AVAILABLE:
            if more_info:
                print("Cython模块不可用，回退到快速解析...")
            return self.parse_file_fast(file_path, more_info)

        file_path = Path(file_path)
        if more_info:
            print(f"开始Cython解析PMX文件: {file_path}")

        # 读取文件数据
        with open(file_path, 'rb') as f:
            data = f.read()

        try:
            # 使用Cython模块解析
            pmx_model = parse_pmx_cython(data, more_info)
            return pmx_model
        except Exception as e:
            raise ValueError(f"PMX文件Cython解析失败: {e}")
    
    def _parse_header(self, data: bytearray) -> PmxHeader:
        """解析PMX文件头
        
        Args:
            data: 文件数据
            
        Returns:
            PMX头信息对象
        """
        # 检查魔数
        magic = self._io_handler.unpack_data("4s", data)[0]
        if magic != b"PMX ":
            print(f"警告: 文件魔数不正确，期望'PMX '，实际'{magic.hex()}'")
        
        # 读取版本号
        version = self._io_handler.unpack_data("f", data)[0]
        version = round(version, 5)  # 修正浮点精度问题
        
        # 读取全局标志数量
        global_flag_count = self._io_handler.unpack_data("B", data)[0]
        if global_flag_count != 8:
            print(f"警告: 全局标志数量异常: {global_flag_count}")
        
        # 读取全局标志
        format_string = f"{global_flag_count}B"
        global_flags = self._io_handler.unpack_data(format_string, data)
        
        # 设置编码类型
        text_encoding = global_flags[0]
        if text_encoding == 0:
            self._use_utf8 = False
            self._io_handler.set_encoding("utf-16le")
        else:
            self._use_utf8 = True
            self._io_handler.set_encoding("utf-8")
        
        # 读取文本信息
        name_jp = self._io_handler.read_variable_string(data)
        name_en = self._io_handler.read_variable_string(data)
        comment_jp = self._io_handler.read_variable_string(data)
        comment_en = self._io_handler.read_variable_string(data)
        
        return PmxHeader(
            version=version,
            name_jp=name_jp,
            name_en=name_en,
            comment_jp=comment_jp,
            comment_en=comment_en
        )
    
    def _setup_parsing_parameters(self, data: bytearray) -> None:
        """设置解析参数

        从全局标志中读取各种索引类型的字节数。
        注意：此方法会保存并恢复读取位置。
        """
        # 保存当前位置
        current_pos = self._io_handler.get_position()

        # 重置到文件开头
        self._io_handler.reset_position()

        # 跳过魔数(4) + 版本号(4) + 标志数量(1) = 9字节
        self._io_handler.skip_bytes(9)

        # 读取全局标志
        global_flags = self._io_handler.unpack_from_buffer("8B")

        # 设置索引格式
        index_formats = {
            1: "B",  # unsigned byte
            2: "H",  # unsigned short
            4: "I"   # unsigned int
        }

        non_vertex_formats = {
            1: "b",  # signed byte
            2: "h",  # signed short
            4: "i"   # signed int
        }

        # 顶点索引（无符号）
        vertex_size = global_flags[2]
        self._vertex_index_format = index_formats.get(vertex_size, "I")

        # 其他索引（有符号）
        tex_size = global_flags[3]
        self._texture_index_format = non_vertex_formats.get(tex_size, "i")

        mat_size = global_flags[4]
        self._material_index_format = non_vertex_formats.get(mat_size, "i")

        bone_size = global_flags[5]
        self._bone_index_format = non_vertex_formats.get(bone_size, "i")

        morph_size = global_flags[6]
        self._morph_index_format = non_vertex_formats.get(morph_size, "i")

        rb_size = global_flags[7]
        self._rigidbody_index_format = non_vertex_formats.get(rb_size, "i")

        # 恢复读取位置
        self._io_handler.set_position(current_pos)

    # ===== 快速解析方法（性能优化版本） =====

    def _parse_header_fast(self) -> PmxHeader:
        """快速解析PMX文件头（使用内部缓冲区）"""
        # 检查魔数
        magic = self._io_handler.unpack_from_buffer("4s")[0]
        if magic != b"PMX ":
            print(f"警告: 文件魔数不正确，期望'PMX '，实际'{magic.hex()}'")

        # 读取版本号
        version = self._io_handler.unpack_from_buffer("f")[0]
        version = round(version, 5)  # 修正浮点精度问题

        # 读取全局标志数量
        global_flag_count = self._io_handler.unpack_from_buffer("B")[0]
        if global_flag_count != 8:
            print(f"警告: 全局标志数量异常: {global_flag_count}")

        # 读取全局标志
        format_string = f"{global_flag_count}B"
        global_flags = self._io_handler.unpack_from_buffer(format_string)

        # 设置编码类型
        text_encoding = global_flags[0]
        if text_encoding == 0:
            self._use_utf8 = False
            self._io_handler.set_encoding("utf-16le")
        else:
            self._use_utf8 = True
            self._io_handler.set_encoding("utf-8")

        # 读取文本信息
        name_jp = self._io_handler.read_variable_string_from_buffer()
        name_en = self._io_handler.read_variable_string_from_buffer()
        comment_jp = self._io_handler.read_variable_string_from_buffer()
        comment_en = self._io_handler.read_variable_string_from_buffer()

        return PmxHeader(
            version=version,
            name_jp=name_jp,
            name_en=name_en,
            comment_jp=comment_jp,
            comment_en=comment_en
        )

    def _setup_parsing_parameters_fast(self) -> None:
        """设置解析参数（快速版本）

        从全局标志中读取各种索引类型的字节数。
        """
        # 保存当前位置
        current_pos = self._io_handler.get_position()

        # 重置到文件开头
        self._io_handler.reset_position()

        # 跳过魔数(4) + 版本号(4) + 标志数量(1) = 9字节
        self._io_handler.skip_bytes(9)

        # 读取全局标志
        global_flags = self._io_handler.unpack_from_buffer("8B")

        # 设置索引格式
        index_formats = {
            1: "B",  # unsigned byte
            2: "H",  # unsigned short
            4: "I"   # unsigned int
        }

        non_vertex_formats = {
            1: "b",  # signed byte
            2: "h",  # signed short
            4: "i"   # signed int
        }

        # 存储附加UV数量
        self._additional_uv_count = global_flags[1]

        # 顶点索引（无符号）
        vertex_size = global_flags[2]
        self._vertex_index_format = index_formats.get(vertex_size, "I")

        # 其他索引（有符号）
        tex_size = global_flags[3]
        self._texture_index_format = non_vertex_formats.get(tex_size, "i")

        mat_size = global_flags[4]
        self._material_index_format = non_vertex_formats.get(mat_size, "i")

        bone_size = global_flags[5]
        self._bone_index_format = non_vertex_formats.get(bone_size, "i")

        morph_size = global_flags[6]
        self._morph_index_format = non_vertex_formats.get(morph_size, "i")

        rb_size = global_flags[7]
        self._rigidbody_index_format = non_vertex_formats.get(rb_size, "i")

        # 恢复读取位置
        self._io_handler.set_position(current_pos)

    def _parse_vertices_fast(self, more_info: bool) -> List[PmxVertex]:
        """快速解析顶点数据（使用内部缓冲区）"""
        # 读取顶点数量
        vertex_count = self._io_handler.unpack_from_buffer("I")[0]
        vertices = []

        if more_info:
            print(f"解析 {vertex_count} 个顶点...")

        # 获取附加UV数量（默认为0）
        additional_uv_count = getattr(self, '_additional_uv_count', 0)

        for i in range(vertex_count):
            # 报告进度
            if i % 1000 == 0:
                self._report_progress(i, vertex_count)

            # 基础顶点数据
            pos_x, pos_y, pos_z = self._io_handler.unpack_from_buffer("3f")
            norm_x, norm_y, norm_z = self._io_handler.unpack_from_buffer("3f")
            uv_u, uv_v = self._io_handler.unpack_from_buffer("2f")

            # 跳过扩展UV
            if additional_uv_count > 0:
                self._io_handler.skip_bytes(additional_uv_count * 16)  # 每个附加UV 4个float

            # 权重模式
            weight_mode_value = self._io_handler.unpack_from_buffer("B")[0]
            weight_mode = WeightMode(weight_mode_value)

            # 权重数据
            weight_data = []
            if weight_mode == WeightMode.BDEF1:
                bone_idx = self._io_handler.unpack_from_buffer(self._bone_index_format)[0]
                weight_data = [[bone_idx, 1.0]]
            elif weight_mode == WeightMode.BDEF2:
                bone1_idx = self._io_handler.unpack_from_buffer(self._bone_index_format)[0]
                bone2_idx = self._io_handler.unpack_from_buffer(self._bone_index_format)[0]
                bone1_weight = self._io_handler.unpack_from_buffer("f")[0]
                weight_data = [[bone1_idx, bone1_weight], [bone2_idx, 1.0 - bone1_weight]]
            elif weight_mode == WeightMode.BDEF4:
                bone_indices = self._io_handler.unpack_from_buffer(f"4{self._bone_index_format}")
                bone_weights = self._io_handler.unpack_from_buffer("4f")
                weight_data = list(zip(bone_indices, bone_weights))
            elif weight_mode == WeightMode.SDEF:
                bone1_idx = self._io_handler.unpack_from_buffer(self._bone_index_format)[0]
                bone2_idx = self._io_handler.unpack_from_buffer(self._bone_index_format)[0]
                bone1_weight = self._io_handler.unpack_from_buffer("f")[0]
                # 跳过SDEF参数（C, R0, R1向量）
                self._io_handler.skip_bytes(36)  # 9 floats = 36 bytes
                weight_data = [[bone1_idx, bone1_weight], [bone2_idx, 1.0 - bone1_weight]]
            elif weight_mode == WeightMode.QDEF:
                # QDEF模式：类似BDEF4
                bone_indices = self._io_handler.unpack_from_buffer(f"4{self._bone_index_format}")
                bone_weights = self._io_handler.unpack_from_buffer("4f")
                weight_data = list(zip(bone_indices, bone_weights))

            # 边缘倍率
            edge_scale = self._io_handler.unpack_from_buffer("f")[0]

            # 创建顶点对象
            vertex = PmxVertex(
                position=[pos_x, pos_y, pos_z],
                normal=[norm_x, norm_y, norm_z],
                uv=[uv_u, uv_v],
                weight_mode=weight_mode,
                weight=weight_data,
                edge_scale=edge_scale
            )

            vertices.append(vertex)

        self._report_progress(vertex_count, vertex_count)
        return vertices

    def _parse_faces_fast(self, more_info: bool) -> List[List[int]]:
        """快速解析面数据（使用内部缓冲区）"""
        # 读取面数量（实际是索引数量）
        index_count = self._io_handler.unpack_from_buffer("I")[0]
        face_count = index_count // 3

        if more_info:
            print(f"解析 {face_count} 个面...")

        faces = []
        format_string = f"3{self._vertex_index_format}"

        for i in range(face_count):
            if i % 1000 == 0:
                self._report_progress(i, face_count)

            indices = list(self._io_handler.unpack_from_buffer(format_string))
            faces.append(indices)

        self._report_progress(face_count, face_count)
        return faces

    def _parse_textures_fast(self, more_info: bool) -> List[str]:
        """快速解析纹理列表（使用内部缓冲区）"""
        texture_count = self._io_handler.unpack_from_buffer("I")[0]
        textures = []

        if more_info:
            print(f"解析 {texture_count} 个纹理...")

        for i in range(texture_count):
            texture_path = self._io_handler.read_variable_string_from_buffer()
            textures.append(texture_path)

        return textures

    def _parse_materials_fast(self, more_info: bool) -> List[PmxMaterial]:
        """快速解析材质数据（使用内部缓冲区）"""
        # 先解析纹理列表
        textures = self._parse_textures_fast(more_info)

        # 读取材质数量
        material_count = self._io_handler.unpack_from_buffer("I")[0]
        materials = []

        if more_info:
            print(f"解析 {material_count} 个材质...")

        for i in range(material_count):
            self._report_progress(i, material_count)

            # 材质名称
            name_jp = self._io_handler.read_variable_string_from_buffer()
            name_en = self._io_handler.read_variable_string_from_buffer()

            # 颜色数据
            diffuse_color = list(self._io_handler.unpack_from_buffer("4f"))
            specular_color = list(self._io_handler.unpack_from_buffer("3f"))
            specular_strength = self._io_handler.unpack_from_buffer("f")[0]
            ambient_color = list(self._io_handler.unpack_from_buffer("3f"))

            # 标志位
            flag_byte = self._io_handler.unpack_from_buffer("B")[0]
            flags_list = [(flag_byte >> j) & 1 == 1 for j in range(8)]
            flags = MaterialFlags(flags_list)

            # 边缘数据
            edge_color = list(self._io_handler.unpack_from_buffer("4f"))
            edge_size = self._io_handler.unpack_from_buffer("f")[0]

            # 纹理索引
            tex_index = self._io_handler.unpack_from_buffer(self._texture_index_format)[0]
            texture_path = textures[tex_index] if 0 <= tex_index < len(textures) else ""

            # 球面纹理索引
            sphere_index = self._io_handler.unpack_from_buffer(self._texture_index_format)[0]
            sphere_path = textures[sphere_index] if 0 <= sphere_index < len(textures) else ""
            sphere_mode = SphMode(self._io_handler.unpack_from_buffer("B")[0])

            # 卡通渲染
            toon_flag = self._io_handler.unpack_from_buffer("B")[0]
            if toon_flag == 0:
                # 使用内置卡通纹理
                toon_index = self._io_handler.unpack_from_buffer("B")[0]
                toon_path = f"toon{toon_index:02d}.bmp"
            else:
                # 使用自定义卡通纹理
                toon_index = self._io_handler.unpack_from_buffer(self._texture_index_format)[0]
                toon_path = textures[toon_index] if 0 <= toon_index < len(textures) else ""

            # 注释和面数
            comment = self._io_handler.read_variable_string_from_buffer()
            face_count = self._io_handler.unpack_from_buffer("I")[0]

            # 创建材质对象
            material = PmxMaterial(
                name_jp=name_jp,
                name_en=name_en,
                diffuse_color=diffuse_color,
                specular_color=specular_color,
                specular_strength=specular_strength,
                ambient_color=ambient_color,
                flags=flags,
                edge_color=edge_color,
                edge_size=edge_size,
                texture_path=texture_path,
                sphere_path=sphere_path,
                sphere_mode=sphere_mode,
                toon_path=toon_path,
                comment=comment,
                face_count=face_count
            )

            materials.append(material)

        self._report_progress(material_count, material_count)
        return materials

    def _parse_vertices(self, data: bytearray) -> List[PmxVertex]:
        """解析顶点数据
        
        Args:
            data: 文件数据
            
        Returns:
            顶点对象列表
        """
        # 读取顶点数量
        vertex_count = self._io_handler.unpack_data("I", data)[0]
        vertices = []
        
        print(f"解析 {vertex_count} 个顶点...")
        
        for i in range(vertex_count):
            # 报告进度
            if i % 1000 == 0:
                self._report_progress(i, vertex_count)
            
            # 基础顶点数据
            pos_x, pos_y, pos_z = self._io_handler.unpack_data("3f", data)
            norm_x, norm_y, norm_z = self._io_handler.unpack_data("3f", data)
            uv_u, uv_v = self._io_handler.unpack_data("2f", data)
            
            # 扩展UV（暂时跳过）
            # TODO: 根据全局标志读取扩展UV
            
            # 权重模式
            weight_mode = WeightMode(self._io_handler.unpack_data("B", data)[0])
            
            # 权重数据（简化处理）
            weight_data = []
            if weight_mode == WeightMode.BDEF1:
                bone_idx = self._io_handler.unpack_data(self._bone_index_format, data)[0]
                weight_data = [[bone_idx, 1.0]]
            elif weight_mode == WeightMode.BDEF2:
                bone1_idx = self._io_handler.unpack_data(self._bone_index_format, data)[0]
                bone2_idx = self._io_handler.unpack_data(self._bone_index_format, data)[0]
                bone1_weight = self._io_handler.unpack_data("f", data)[0]
                weight_data = [[bone1_idx, bone1_weight], [bone2_idx, 1.0 - bone1_weight]]
            elif weight_mode == WeightMode.BDEF4:
                bone_indices = self._io_handler.unpack_data(f"4{self._bone_index_format}", data)
                bone_weights = self._io_handler.unpack_data("4f", data)
                weight_data = list(zip(bone_indices, bone_weights))
            elif weight_mode == WeightMode.SDEF:
                # SDEF需要额外的C、R0、R1向量
                bone1_idx = self._io_handler.unpack_data(self._bone_index_format, data)[0]
                bone2_idx = self._io_handler.unpack_data(self._bone_index_format, data)[0]
                bone1_weight = self._io_handler.unpack_data("f", data)[0]
                # 跳过SDEF参数
                self._io_handler.unpack_data("9f", data)  # C, R0, R1向量
                weight_data = [[bone1_idx, bone1_weight], [bone2_idx, 1.0 - bone1_weight]]
            
            # 边缘倍率
            edge_scale = self._io_handler.unpack_data("f", data)[0]
            
            # 创建顶点对象
            vertex = PmxVertex(
                position=[pos_x, pos_y, pos_z],
                normal=[norm_x, norm_y, norm_z],
                uv=[uv_u, uv_v],
                weight_mode=weight_mode,
                weight=weight_data,
                edge_scale=edge_scale
            )
            
            vertices.append(vertex)
        
        self._report_progress(vertex_count, vertex_count)
        return vertices
    
    def _parse_faces(self, data: bytearray) -> List[List[int]]:
        """解析面数据
        
        Args:
            data: 文件数据
            
        Returns:
            面索引列表
        """
        # 读取面数量（实际是索引数量）
        index_count = self._io_handler.unpack_data("I", data)[0]
        face_count = index_count // 3
        
        print(f"解析 {face_count} 个面...")
        
        faces = []
        format_string = f"3{self._vertex_index_format}"
        
        for i in range(face_count):
            if i % 1000 == 0:
                self._report_progress(i, face_count)
            
            indices = list(self._io_handler.unpack_data(format_string, data))
            faces.append(indices)

        self._report_progress(face_count, face_count)
        return faces

    def _parse_textures(self, data: bytearray) -> List[str]:
        """解析纹理列表

        Args:
            data: 文件数据

        Returns:
            纹理路径列表
        """
        texture_count = self._io_handler.unpack_data("I", data)[0]
        textures = []

        print(f"解析 {texture_count} 个纹理...")

        for i in range(texture_count):
            texture_path = self._io_handler.read_variable_string(data)
            textures.append(texture_path)

        return textures

    def _parse_materials(self, data: bytearray) -> List[PmxMaterial]:
        """解析材质数据

        Args:
            data: 文件数据

        Returns:
            材质对象列表
        """
        # 先解析纹理列表
        textures = self._parse_textures(data)
        # 读取材质数量
        material_count = self._io_handler.unpack_data("I", data)[0]
        materials = []
        
        print(f"解析 {material_count} 个材质...")
        
        for i in range(material_count):
            self._report_progress(i, material_count)
            
            # 材质名称
            name_jp = self._io_handler.read_variable_string(data)
            name_en = self._io_handler.read_variable_string(data)
            
            # 颜色数据
            diffuse_color = list(self._io_handler.unpack_data("4f", data))
            specular_color = list(self._io_handler.unpack_data("3f", data))
            specular_strength = self._io_handler.unpack_data("f", data)[0]
            ambient_color = list(self._io_handler.unpack_data("3f", data))
            
            # 标志位
            flag_byte = self._io_handler.unpack_data("B", data)[0]
            flags_list = [(flag_byte >> j) & 1 == 1 for j in range(8)]
            flags = MaterialFlags(flags_list)
            
            # 边缘数据
            edge_color = list(self._io_handler.unpack_data("4f", data))
            edge_size = self._io_handler.unpack_data("f", data)[0]

            # 纹理索引
            tex_index = self._io_handler.unpack_data(self._texture_index_format, data)[0]
            texture_path = textures[tex_index] if 0 <= tex_index < len(textures) else ""

            # 球面纹理索引
            sphere_index = self._io_handler.unpack_data(self._texture_index_format, data)[0]
            sphere_path = textures[sphere_index] if 0 <= sphere_index < len(textures) else ""
            sphere_mode = SphMode(self._io_handler.unpack_data("B", data)[0])

            # 卡通渲染
            toon_flag = self._io_handler.unpack_data("B", data)[0]
            if toon_flag == 0:
                # 使用内置卡通纹理
                toon_index = self._io_handler.unpack_data("B", data)[0]
                toon_path = f"toon{toon_index:02d}.bmp"
            else:
                # 使用自定义卡通纹理
                toon_index = self._io_handler.unpack_data(self._texture_index_format, data)[0]
                toon_path = textures[toon_index] if 0 <= toon_index < len(textures) else ""
            
            # 注释和面数
            comment = self._io_handler.read_variable_string(data)
            face_count = self._io_handler.unpack_data("I", data)[0]
            
            # 创建材质对象
            material = PmxMaterial(
                name_jp=name_jp,
                name_en=name_en,
                diffuse_color=diffuse_color,
                specular_color=specular_color,
                specular_strength=specular_strength,
                ambient_color=ambient_color,
                flags=flags,
                edge_color=edge_color,
                edge_size=edge_size,
                texture_path=texture_path,
                sphere_path=sphere_path,
                sphere_mode=sphere_mode,
                toon_path=toon_path,
                comment=comment,
                face_count=face_count
            )
            
            materials.append(material)
        
        self._report_progress(material_count, material_count)
        return materials
    
    def write_file(self, pmx_model: PmxModel, 
                  file_path: Union[str, Path]) -> None:
        """写入PMX文件
        
        Args:
            pmx_model: PMX模型对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入PMX文件: {file_path}")
        
        # 验证模型数据
        pmx_model.validate()
        
        # 准备写入数据
        self._setup_encoding_parameters(pmx_model)
        
        # 构建二进制数据
        binary_data = bytearray()
        
        try:
            # 预分析数据以确定索引大小
            lookahead_data = self._analyze_model_data(pmx_model)
            texture_list = self._build_texture_list(pmx_model)
            
            # 设置索引大小变量
            self._vertex_index_size = lookahead_data['vertex_index_size']
            self._material_index_size = lookahead_data['material_index_size']
            
            # 编码各个部分
            print("编码PMX头部...")
            binary_data.extend(self._encode_header(pmx_model.header, lookahead_data))
            
            print("编码顶点数据...")
            binary_data.extend(self._encode_vertices(pmx_model.vertices))
            
            print("编码面数据...")
            binary_data.extend(self._encode_faces(pmx_model.faces))
            
            print("编码纹理列表...")
            binary_data.extend(self._encode_textures(texture_list))
            
            print("编码材质数据...")
            binary_data.extend(self._encode_materials(pmx_model.materials, texture_list))
            
            # 写入文件
            self._io_handler.write_file(file_path, bytes(binary_data))
            
            print(f"PMX文件写入完成，总大小: {len(binary_data)}字节")
            
        except Exception as e:
            raise ValueError(f"PMX文件写入失败: {e}") from e
    
    def _setup_encoding_parameters(self, pmx_model: PmxModel) -> None:
        """设置编码参数"""
        # 根据模型头部设置编码格式
        if hasattr(pmx_model.header, 'text_encoding') and pmx_model.header.text_encoding == 0:
            self._use_utf8 = False
            self._io_handler.set_encoding("utf-16le")
        else:
            self._use_utf8 = True
            self._io_handler.set_encoding("utf-8")
    
    def _analyze_model_data(self, pmx_model: PmxModel) -> dict:
        """分析模型数据以确定最优索引大小"""
        return {
            'vertex_count': len(pmx_model.vertices),
            'material_count': len(pmx_model.materials),
            'vertex_index_size': self._determine_index_size(len(pmx_model.vertices)),
            'material_index_size': self._determine_index_size(len(pmx_model.materials)),
        }
    
    def _determine_index_size(self, count: int) -> int:
        """确定索引大小（1、2或4字节）"""
        if count < 256:
            return 1
        elif count < 65536:
            return 2
        else:
            return 4
    
    def _build_texture_list(self, pmx_model: PmxModel) -> List[str]:
        """构建去重的纹理路径列表"""
        texture_set = set()
        texture_list = []
        
        for material in pmx_model.materials:
            # 添加主纹理
            if hasattr(material, 'texture_path') and material.texture_path and material.texture_path not in texture_set:
                texture_set.add(material.texture_path)
                texture_list.append(material.texture_path)
            
            # 添加球面纹理
            if hasattr(material, 'sphere_path') and material.sphere_path and material.sphere_path not in texture_set:
                texture_set.add(material.sphere_path)
                texture_list.append(material.sphere_path)
            
            # 添加toon纹理
            if hasattr(material, 'toon_path') and material.toon_path and material.toon_path not in texture_set:
                texture_set.add(material.toon_path)
                texture_list.append(material.toon_path)
        
        return texture_list
    
    def _encode_header(self, header: PmxHeader, lookahead_data: dict) -> bytes:
        """编码PMX头部"""
        data = bytearray()
        
        # PMX魔术字符串和版本
        data.extend(b"PMX ")
        data.extend(self._io_handler.pack_data("<f", header.version))
        
        # 全局配置标志
        global_flags = bytearray([
            1 if self._use_utf8 else 0,  # 文本编码
            4,  # 附加UV数量（固定为4）
            lookahead_data['vertex_index_size'],    # 顶点索引大小
            1,   # 纹理索引大小（固定为1字节）
            lookahead_data['material_index_size'],  # 材质索引大小
            1,   # 骨骼索引大小（固定为1字节）
            1,   # 变形索引大小（固定为1字节）
            1    # 刚体索引大小（固定为1字节）
        ])
        
        data.extend(struct.pack("<B", len(global_flags)))
        data.extend(global_flags)
        
        # 模型信息
        data.extend(self._io_handler.write_variable_string(header.name_jp))
        data.extend(self._io_handler.write_variable_string(header.name_en))
        data.extend(self._io_handler.write_variable_string(header.comment_jp))
        data.extend(self._io_handler.write_variable_string(header.comment_en))
        
        return bytes(data)
    
    def _encode_vertices(self, vertices: List[PmxVertex]) -> bytes:
        """编码顶点数据"""
        data = bytearray()
        
        # 顶点数量
        data.extend(self._io_handler.pack_data("<I", len(vertices)))
        
        for vertex in vertices:
            # 位置
            data.extend(self._io_handler.pack_data("<3f", *vertex.position))
            
            # 法线
            data.extend(self._io_handler.pack_data("<3f", *vertex.normal))
            
            # UV坐标
            data.extend(self._io_handler.pack_data("<2f", *vertex.uv))
            
            # 附加UV（暂时写入零值）
            for _ in range(4):  # 4个附加UV
                data.extend(self._io_handler.pack_data("<4f", 0.0, 0.0, 0.0, 0.0))
            
            # 权重类型（简化处理，使用BDEF1）
            data.extend(self._io_handler.pack_data("<B", 0))  # BDEF1
            data.extend(self._io_handler.pack_data("<I", 0))  # 骨骼索引0
            
            # 边缘倍率
            data.extend(self._io_handler.pack_data("<f", getattr(vertex, 'edge_scale', 1.0)))
        
        return bytes(data)
    
    def _encode_faces(self, faces: List[List[int]]) -> bytes:
        """编码面数据"""
        data = bytearray()
        
        # 面索引数量（每个面3个索引）
        index_count = len(faces) * 3
        data.extend(self._io_handler.pack_data("<I", index_count))
        
        # 面索引数据
        for face in faces:
            for vertex_index in face:
                # 使用确定的索引大小写入
                if self._vertex_index_size == 1:
                    data.extend(self._io_handler.pack_data("<B", vertex_index))
                elif self._vertex_index_size == 2:
                    data.extend(self._io_handler.pack_data("<H", vertex_index))
                else:  # 4
                    data.extend(self._io_handler.pack_data("<I", vertex_index))
        
        return bytes(data)
    
    def _encode_textures(self, texture_list: List[str]) -> bytes:
        """编码纹理列表"""
        data = bytearray()
        
        # 纹理数量
        data.extend(self._io_handler.pack_data("<I", len(texture_list)))
        
        # 纹理路径
        for texture_path in texture_list:
            data.extend(self._io_handler.write_variable_string(texture_path))
        
        return bytes(data)
    
    def _encode_materials(self, materials: List[PmxMaterial], texture_list: List[str]) -> bytes:
        """编码材质数据"""
        data = bytearray()
        
        # 材质数量
        data.extend(self._io_handler.pack_data("<I", len(materials)))
        
        for material in materials:
            # 材质名称
            data.extend(self._io_handler.write_variable_string(getattr(material, 'name_jp', '')))
            data.extend(self._io_handler.write_variable_string(getattr(material, 'name_en', '')))
            
            # 漫反射颜色
            diffuse = getattr(material, 'diffuse_color', [1.0, 1.0, 1.0, 1.0])
            if len(diffuse) == 3:
                diffuse = [diffuse[0], diffuse[1], diffuse[2], 1.0]
            data.extend(self._io_handler.pack_data("<4f", diffuse[0], diffuse[1], diffuse[2], diffuse[3]))
            
            # 镜面反射颜色和强度
            specular = getattr(material, 'specular_color', [1.0, 1.0, 1.0])
            specular_strength = getattr(material, 'specular_strength', 0.0)
            data.extend(self._io_handler.pack_data("<4f", specular[0], specular[1], specular[2], specular_strength))
            
            # 环境光颜色
            ambient = getattr(material, 'ambient_color', [1.0, 1.0, 1.0])
            data.extend(self._io_handler.pack_data("<3f", *ambient))
            
            # 材质标志（简化处理）
            flags = 0x01  # 默认启用双面渲染
            data.extend(self._io_handler.pack_data("<B", flags))
            
            # 边缘颜色和大小
            edge_color = getattr(material, 'edge_color', [0.0, 0.0, 0.0, 1.0])
            edge_size = getattr(material, 'edge_size', 1.0)
            data.extend(self._io_handler.pack_data("<4f", *edge_color))
            data.extend(self._io_handler.pack_data("<f", edge_size))
            
            # 纹理索引（简化处理）
            tex_diffuse_idx = -1
            if hasattr(material, 'texture_path') and material.texture_path:
                try:
                    tex_diffuse_idx = texture_list.index(material.texture_path)
                except ValueError:
                    tex_diffuse_idx = -1
            
            data.extend(self._io_handler.pack_data("<b", tex_diffuse_idx))
            
            # 球面纹理索引和模式
            data.extend(self._io_handler.pack_data("<b", -1))  # 无球面纹理
            data.extend(self._io_handler.pack_data("<B", 0))   # 球面模式：禁用
            
            # Toon模式和纹理
            data.extend(self._io_handler.pack_data("<B", 0))   # Toon模式：共享
            data.extend(self._io_handler.pack_data("<B", 0))   # Toon纹理索引
            
            # 备注
            data.extend(self._io_handler.write_variable_string(""))
            
            # 面数量
            face_count = getattr(material, 'face_count', 0)
            data.extend(self._io_handler.pack_data("<I", face_count))
        
        return bytes(data)
    
    # ===== 文本解析和导出功能 =====
    
    def parse_text_file(self, file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
        """解析PMX文本文件
        
        Args:
            file_path: 文本文件路径
            more_info: 是否显示详细信息
            
        Returns:
            解析后的PMX模型对象
            
        Raises:
            ValueError: 文件格式错误
            FileNotFoundError: 文件不存在
        """
        file_path = Path(file_path)
        if more_info:
            print(f"开始解析PMX文本文件: {file_path}")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip().split('\t') if '\t' in line else [line.strip()] 
                    for line in f.readlines() if line.strip()]
        
        if more_info:
            print(f"文本文件总行数: {len(lines)}")
            
        line_idx = 0
        
        try:
            # 解析头部
            header, line_idx = self._parse_text_header(lines, line_idx)
            
            # 解析顶点
            vertices, line_idx = self._parse_text_vertices(lines, line_idx, more_info)
            
            # 解析面
            faces, line_idx = self._parse_text_faces(lines, line_idx, more_info)
            
            # 解析材质
            materials, line_idx = self._parse_text_materials(lines, line_idx, more_info)
            
        except (ValueError, IndexError) as e:
            raise ValueError(f"PMX文本文件解析失败在第{line_idx + 1}行: {e}")
        
        if more_info:
            print(f"PMX文本解析完成")
        
        # 创建并返回PMX模型
        model = PmxModel()
        model.header = header
        model.vertices = vertices
        model.faces = faces
        model.materials = materials
        
        return model
    
    def write_text_file(self, model: PmxModel, file_path: Union[str, Path]) -> None:
        """将PMX模型数据导出为文本文件
        
        Args:
            model: PMX模型对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        print(f"开始写入PMX文本文件: {file_path}")
        
        lines = []
        
        # 写入头部
        lines.extend(self._format_text_header(model.header))
        
        # 写入顶点
        lines.extend(self._format_text_vertices(model.vertices))
        
        # 写入面
        lines.extend(self._format_text_faces(model.faces))
        
        # 写入材质
        lines.extend(self._format_text_materials(model.materials))
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"PMX文本文件写入完成，总行数: {len(lines)}")
    
    def _parse_text_header(self, lines: List[List[str]], start_idx: int) -> tuple:
        """解析PMX文本头部"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "version:":
            raise ValueError("缺少版本信息")
        version = float(lines[start_idx][1])
        
        if start_idx + 1 >= len(lines) or len(lines[start_idx + 1]) != 2 or lines[start_idx + 1][0] != "name_jp:":
            raise ValueError("缺少日语名称")
        name_jp = lines[start_idx + 1][1]
        
        if start_idx + 2 >= len(lines) or len(lines[start_idx + 2]) != 2 or lines[start_idx + 2][0] != "name_en:":
            raise ValueError("缺少英语名称")
        name_en = lines[start_idx + 2][1]
        
        if start_idx + 3 >= len(lines) or len(lines[start_idx + 3]) != 2 or lines[start_idx + 3][0] != "comment_jp:":
            raise ValueError("缺少日语备注")
        comment_jp = lines[start_idx + 3][1]
        
        if start_idx + 4 >= len(lines) or len(lines[start_idx + 4]) != 2 or lines[start_idx + 4][0] != "comment_en:":
            raise ValueError("缺少英语备注")
        comment_en = lines[start_idx + 4][1]
        
        header = PmxHeader(
            version=version,
            name_jp=name_jp,
            name_en=name_en,
            comment_jp=comment_jp,
            comment_en=comment_en
        )
        
        return header, start_idx + 5
    
    def _parse_text_vertices(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析顶点数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "vertex_count:":
            raise ValueError("缺少顶点计数")
        
        vertex_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"顶点数量: {vertex_count}")
        
        vertices = []
        if vertex_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("顶点数据不完整")
            line_idx += 1
            
            for i in range(vertex_count):
                if line_idx >= len(lines):
                    raise ValueError(f"顶点数据不完整，期望{vertex_count}个顶点，只找到{i}个")
                
                row = lines[line_idx]
                if len(row) < 8:  # 至少需要位置、法线和UV数据
                    raise ValueError(f"顶点格式错误，期望至少8个字段，得到{len(row)}个")
                
                vertex = PmxVertex(
                    position=[float(row[0]), float(row[1]), float(row[2])],
                    normal=[float(row[3]), float(row[4]), float(row[5])],
                    uv=[float(row[6]), float(row[7])]
                )
                vertices.append(vertex)
                line_idx += 1
        
        return vertices, line_idx
    
    def _parse_text_faces(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析面数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "face_count:":
            raise ValueError("缺少面计数")
        
        face_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"面数量: {face_count}")
        
        faces = []
        if face_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("面数据不完整")
            line_idx += 1
            
            for i in range(face_count):
                if line_idx >= len(lines):
                    raise ValueError(f"面数据不完整，期望{face_count}个面，只找到{i}个")
                
                row = lines[line_idx]
                if len(row) != 3:
                    raise ValueError(f"面格式错误，期望3个顶点索引，得到{len(row)}个")
                
                face = [int(row[0]), int(row[1]), int(row[2])]
                faces.append(face)
                line_idx += 1
        
        return faces, line_idx
    
    def _parse_text_materials(self, lines: List[List[str]], start_idx: int, more_info: bool) -> tuple:
        """解析材质数据"""
        if start_idx >= len(lines) or len(lines[start_idx]) != 2 or lines[start_idx][0] != "material_count:":
            raise ValueError("缺少材质计数")
        
        material_count = int(lines[start_idx][1])
        line_idx = start_idx + 1
        
        if more_info:
            print(f"材质数量: {material_count}")
        
        materials = []
        if material_count > 0:
            # 跳过键名行
            if line_idx >= len(lines):
                raise ValueError("材质数据不完整")
            line_idx += 1
            
            for i in range(material_count):
                if line_idx >= len(lines):
                    raise ValueError(f"材质数据不完整，期望{material_count}个材质，只找到{i}个")
                
                row = lines[line_idx]
                if len(row) < 15:  # 基本材质信息
                    raise ValueError(f"材质格式错误，期望至少15个字段，得到{len(row)}个")
                
                material = PmxMaterial(
                    name_jp=row[0],
                    name_en=row[1],
                    diffuse_color=[float(row[2]), float(row[3]), float(row[4]), float(row[5])],
                    specular_color=[float(row[6]), float(row[7]), float(row[8])],
                    specular_strength=float(row[9]),
                    ambient_color=[float(row[10]), float(row[11]), float(row[12])],
                    texture_path=row[13] if row[13] != "null" else "",
                    face_count=int(row[14])
                )
                materials.append(material)
                line_idx += 1
        
        return materials, line_idx
    
    def _format_text_header(self, header: PmxHeader) -> List[str]:
        """格式化头部为文本"""
        return [
            f"version:\t{header.version}",
            f"name_jp:\t{header.name_jp}",
            f"name_en:\t{header.name_en}",
            f"comment_jp:\t{header.comment_jp}",
            f"comment_en:\t{header.comment_en}"
        ]
    
    def _format_text_vertices(self, vertices: List[PmxVertex]) -> List[str]:
        """格式化顶点为文本"""
        lines = [f"vertex_count:\t{len(vertices)}"]
        
        if vertices:
            # 键名行
            keys = ["pos_x", "pos_y", "pos_z", "norm_x", "norm_y", "norm_z", "uv_u", "uv_v"]
            lines.append('\t'.join(keys))
            
            for vertex in vertices:
                row = [
                    f"{vertex.position[0]:.6f}",
                    f"{vertex.position[1]:.6f}",
                    f"{vertex.position[2]:.6f}",
                    f"{vertex.normal[0]:.6f}",
                    f"{vertex.normal[1]:.6f}",
                    f"{vertex.normal[2]:.6f}",
                    f"{vertex.uv[0]:.6f}",
                    f"{vertex.uv[1]:.6f}"
                ]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_faces(self, faces: List[List[int]]) -> List[str]:
        """格式化面为文本"""
        lines = [f"face_count:\t{len(faces)}"]
        
        if faces:
            lines.append('\t'.join(["vertex_0", "vertex_1", "vertex_2"]))
            
            for face in faces:
                row = [str(face[0]), str(face[1]), str(face[2])]
                lines.append('\t'.join(row))
        
        return lines
    
    def _format_text_materials(self, materials: List[PmxMaterial]) -> List[str]:
        """格式化材质为文本"""
        lines = [f"material_count:\t{len(materials)}"]
        
        if materials:
            keys = ["name_jp", "name_en", "diff_r", "diff_g", "diff_b", "diff_a",
                   "spec_r", "spec_g", "spec_b", "spec_strength", 
                   "amb_r", "amb_g", "amb_b", "texture", "face_count"]
            lines.append('\t'.join(keys))
            
            for material in materials:
                row = [
                    material.name_jp,
                    material.name_en,
                    f"{material.diffuse_color[0]:.6f}",
                    f"{material.diffuse_color[1]:.6f}",
                    f"{material.diffuse_color[2]:.6f}",
                    f"{material.diffuse_color[3]:.6f}",
                    f"{material.specular_color[0]:.6f}",
                    f"{material.specular_color[1]:.6f}",
                    f"{material.specular_color[2]:.6f}",
                    f"{material.specular_strength:.6f}",
                    f"{material.ambient_color[0]:.6f}",
                    f"{material.ambient_color[1]:.6f}",
                    f"{material.ambient_color[2]:.6f}",
                    material.texture_path if material.texture_path else "null",
                    str(material.face_count)
                ]
                lines.append('\t'.join(row))
        
        return lines
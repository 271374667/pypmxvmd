# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False
"""
PyPMXVMD PMX快速解析模块 (Cython优化)

提供高性能的PMX文件解析功能。
返回与原有API兼容的PmxModel, PmxVertex等对象。
"""

from libc.string cimport memcpy
from libc.math cimport round
from cpython.bytes cimport PyBytes_AS_STRING
from cpython.unicode cimport PyUnicode_Decode

# 导入原有数据模型
from pypmxvmd.common.models.pmx import (
    PmxModel, PmxHeader, PmxVertex, PmxMaterial, WeightMode, SphMode, MaterialFlags
)


cdef class FastPmxReader:
    """PMX快速读取器"""
    cdef bytes _data
    cdef const unsigned char* _ptr
    cdef int _pos
    cdef int _size
    cdef str _encoding
    
    # 编码查找优化
    cdef const char* _encoding_c_str

    # 索引大小
    cdef int _additional_uv_count
    cdef int _vertex_index_size
    cdef int _texture_index_size
    cdef int _material_index_size
    cdef int _bone_index_size
    cdef int _morph_index_size
    cdef int _rigidbody_index_size

    def __init__(self, bytes data):
        self._data = data
        self._ptr = <const unsigned char*>PyBytes_AS_STRING(data)
        self._pos = 0
        self._size = len(data)
        self._encoding = "utf-16le"
        self._encoding_c_str = "utf-16le"

        # 默认索引大小
        self._additional_uv_count = 0
        self._vertex_index_size = 1
        self._texture_index_size = 1
        self._material_index_size = 1
        self._bone_index_size = 1
        self._morph_index_size = 1
        self._rigidbody_index_size = 1

    cdef inline unsigned char read_byte(self):
        """读取无符号字节"""
        cdef unsigned char value = self._ptr[self._pos]
        self._pos += 1
        return value

    cdef inline signed char read_sbyte(self):
        """读取有符号字节"""
        cdef signed char value = <signed char>self._ptr[self._pos]
        self._pos += 1
        return value

    cdef inline unsigned short read_ushort(self):
        """读取无符号短整数"""
        cdef unsigned short value
        memcpy(&value, self._ptr + self._pos, 2)
        self._pos += 2
        return value

    cdef inline short read_short(self):
        """读取有符号短整数"""
        cdef short value
        memcpy(&value, self._ptr + self._pos, 2)
        self._pos += 2
        return value

    cdef inline unsigned int read_uint(self):
        """读取无符号整数"""
        cdef unsigned int value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cdef inline int read_int(self):
        """读取有符号整数"""
        cdef int value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cdef inline float read_float(self):
        """读取浮点数"""
        cdef float value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cdef inline void skip(self, int count):
        """跳过字节"""
        self._pos += count

    cdef inline bytes read_bytes(self, int count):
        """读取字节"""
        cdef bytes result = self._data[self._pos:self._pos + count]
        self._pos += count
        return result

    cdef str read_variable_string(self):
        """读取变长字符串 (零拷贝优化)"""
        cdef unsigned int length
        memcpy(&length, self._ptr + self._pos, 4)
        self._pos += 4
        
        if length == 0:
            return ""

        cdef const char* start = <const char*>(self._ptr + self._pos)
        self._pos += length

        # 直接使用C API解码，避免创建临时bytes对象
        return PyUnicode_Decode(start, length, self._encoding_c_str, "ignore")

    cdef int read_vertex_index(self):
        """读取顶点索引（无符号）"""
        if self._vertex_index_size == 1:
            return self.read_byte()
        elif self._vertex_index_size == 2:
            return self.read_ushort()
        else:
            return self.read_uint()
    
    # 内联优化的专用读取函数，避免函数调用开销
    cdef inline int _read_bone_index_fast(self, int size):
        cdef int val
        if size == 1:
            val = <signed char>self._ptr[self._pos]
            self._pos += 1
            return val
        elif size == 2:
            return self.read_short() # 还是调这个吧，memcpy安全点
        else:
            memcpy(&val, self._ptr + self._pos, 4)
            self._pos += 4
            return val

    cdef int read_bone_index(self):
        """读取骨骼索引（有符号）"""
        if self._bone_index_size == 1:
            return self.read_sbyte()
        elif self._bone_index_size == 2:
            return self.read_short()
        else:
            return self.read_int()

    cdef int read_texture_index(self):
        """读取纹理索引（有符号）"""
        if self._texture_index_size == 1:
            return self.read_sbyte()
        elif self._texture_index_size == 2:
            return self.read_short()
        else:
            return self.read_int()


cpdef parse_pmx_cython(bytes data, bint more_info=False):
    """使用Cython解析PMX文件数据

    Args:
        data: PMX文件的二进制数据
        more_info: 是否显示详细信息

    Returns:
        PmxModel对象 (与原有API完全兼容)
    """
    cdef FastPmxReader reader = FastPmxReader(data)

    # 解析头部魔数
    cdef bytes magic = reader.read_bytes(4)
    if magic != b'PMX ':
        raise ValueError(f"无效的PMX魔术字符串: '{magic}'")

    # 读取版本号
    cdef float version = reader.read_float()
    version = round(version * 100000.0) / 100000.0  # 修正浮点精度

    # 读取全局标志
    cdef unsigned char flag_count = reader.read_byte()
    if flag_count != 8:
        print(f"警告: 全局标志数量异常: {flag_count}")

    # 读取全局标志值
    cdef unsigned char text_encoding = reader.read_byte()
    reader._additional_uv_count = reader.read_byte()
    reader._vertex_index_size = reader.read_byte()
    reader._texture_index_size = reader.read_byte()
    reader._material_index_size = reader.read_byte()
    reader._bone_index_size = reader.read_byte()
    reader._morph_index_size = reader.read_byte()
    reader._rigidbody_index_size = reader.read_byte()

    # 设置编码
    if text_encoding == 0:
        reader._encoding = "utf-16le"
        reader._encoding_c_str = "utf-16le"
    else:
        reader._encoding = "utf-8"
        reader._encoding_c_str = "utf-8"

    # 读取模型信息
    cdef str name_jp = reader.read_variable_string()
    cdef str name_en = reader.read_variable_string()
    cdef str comment_jp = reader.read_variable_string()
    cdef str comment_en = reader.read_variable_string()

    # 创建PMX对象
    cdef object pmx = PmxModel()
    pmx.header = PmxHeader(
        version=version,
        name_jp=name_jp,
        name_en=name_en,
        comment_jp=comment_jp,
        comment_en=comment_en
    )

    # 解析顶点
    pmx.vertices = _parse_vertices_cython(reader, more_info)

    # 解析面
    pmx.faces = _parse_faces_cython(reader, more_info)

    # 解析纹理和材质
    cdef list textures = _parse_textures_cython(reader, more_info)
    pmx.textures = textures
    pmx.materials = _parse_materials_cython(reader, textures, more_info)

    if more_info:
        print(f"PMX Cython解析完成: {len(pmx.vertices)}个顶点, "
              f"{len(pmx.faces)}个面, {len(pmx.materials)}个材质")

    return pmx


cdef list _parse_vertices_cython(FastPmxReader reader, bint more_info):
    """解析顶点数据 (Cython优化)"""
    cdef unsigned int vertex_count = reader.read_uint()
    # 预分配列表
    cdef list vertices = [None] * vertex_count

    if more_info:
        print(f"解析 {vertex_count} 个顶点...")

    cdef unsigned int i
    cdef float px, py, pz, nx, ny, nz, u, v, edge_scale
    cdef float weight1, weight2
    cdef unsigned char weight_mode
    cdef int bone1, bone2, bone3, bone4
    cdef float w1, w2, w3, w4
    cdef list weight_data
    cdef int additional_uv_count = reader._additional_uv_count
    
    # 缓存索引大小变量以减少属性访问
    cdef int bone_idx_size_local = reader._bone_index_size

    for i in range(vertex_count):
        # 位置
        memcpy(&px, reader._ptr + reader._pos, 4)
        memcpy(&py, reader._ptr + reader._pos + 4, 4)
        memcpy(&pz, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 法线
        memcpy(&nx, reader._ptr + reader._pos, 4)
        memcpy(&ny, reader._ptr + reader._pos + 4, 4)
        memcpy(&nz, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # UV
        memcpy(&u, reader._ptr + reader._pos, 4)
        memcpy(&v, reader._ptr + reader._pos + 4, 4)
        reader._pos += 8

        # 跳过附加UV
        if additional_uv_count > 0:
            reader._pos += additional_uv_count * 16  # 每个附加UV 4个float

        # 权重模式
        weight_mode = reader._ptr[reader._pos]
        reader._pos += 1

        # 权重数据
        if weight_mode == 0:  # BDEF1
            bone1 = reader._read_bone_index_fast(bone_idx_size_local)
            weight_data = [[bone1, 1.0]]
        elif weight_mode == 1:  # BDEF2
            bone1 = reader._read_bone_index_fast(bone_idx_size_local)
            bone2 = reader._read_bone_index_fast(bone_idx_size_local)
            # 浮点数读取优化
            memcpy(&weight1, reader._ptr + reader._pos, 4)
            reader._pos += 4
            weight_data = [[bone1, weight1], [bone2, 1.0 - weight1]]
        elif weight_mode == 2:  # BDEF4
            bone1 = reader._read_bone_index_fast(bone_idx_size_local)
            bone2 = reader._read_bone_index_fast(bone_idx_size_local)
            bone3 = reader._read_bone_index_fast(bone_idx_size_local)
            bone4 = reader._read_bone_index_fast(bone_idx_size_local)
            
            memcpy(&w1, reader._ptr + reader._pos, 4)
            memcpy(&w2, reader._ptr + reader._pos + 4, 4)
            memcpy(&w3, reader._ptr + reader._pos + 8, 4)
            memcpy(&w4, reader._ptr + reader._pos + 12, 4)
            reader._pos += 16
            
            weight_data = [[bone1, w1], [bone2, w2], [bone3, w3], [bone4, w4]]
        elif weight_mode == 3:  # SDEF
            bone1 = reader._read_bone_index_fast(bone_idx_size_local)
            bone2 = reader._read_bone_index_fast(bone_idx_size_local)
            memcpy(&weight1, reader._ptr + reader._pos, 4)
            reader._pos += 4
            # 跳过SDEF参数 (C, R0, R1向量)
            reader._pos += 36  # 9 floats = 36 bytes
            weight_data = [[bone1, weight1], [bone2, 1.0 - weight1]]
        elif weight_mode == 4:  # QDEF
            bone1 = reader._read_bone_index_fast(bone_idx_size_local)
            bone2 = reader._read_bone_index_fast(bone_idx_size_local)
            bone3 = reader._read_bone_index_fast(bone_idx_size_local)
            bone4 = reader._read_bone_index_fast(bone_idx_size_local)
            
            memcpy(&w1, reader._ptr + reader._pos, 4)
            memcpy(&w2, reader._ptr + reader._pos + 4, 4)
            memcpy(&w3, reader._ptr + reader._pos + 8, 4)
            memcpy(&w4, reader._ptr + reader._pos + 12, 4)
            reader._pos += 16
            
            weight_data = [[bone1, w1], [bone2, w2], [bone3, w3], [bone4, w4]]
        else:
             weight_data = [] # 防止未初始化

        # 边缘倍率
        memcpy(&edge_scale, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 创建顶点对象
        # 直接使用列表预分配
        vertices[i] = PmxVertex(
            position=[px, py, pz],
            normal=[nx, ny, nz],
            uv=[u, v],
            weight_mode=WeightMode(weight_mode),
            weight=weight_data,
            edge_scale=edge_scale
        )

    return vertices


cdef list _parse_faces_cython(FastPmxReader reader, bint more_info):
    """解析面数据 (Cython优化)"""
    cdef unsigned int index_count = reader.read_uint()
    cdef unsigned int face_count = index_count // 3
    # 预分配
    cdef list faces = [None] * face_count

    if more_info:
        print(f"解析 {face_count} 个面...")

    cdef unsigned int i
    cdef int v0, v1, v2
    # 增加 unsigned short 变量用于正确读取 2 字节索引
    cdef unsigned short us0, us1, us2
    cdef int vertex_index_size = reader._vertex_index_size
    cdef const unsigned char* ptr = reader._ptr

    # 将常用判断提出来分三种循环处理，避免每次循环都判断一次if/else
    if vertex_index_size == 1:
        for i in range(face_count):
            v0 = ptr[reader._pos]
            v1 = ptr[reader._pos + 1]
            v2 = ptr[reader._pos + 2]
            reader._pos += 3
            faces[i] = [v0, v1, v2]
    elif vertex_index_size == 2:
        for i in range(face_count):
            # 修正: 使用 unsigned short 过渡，避免直接 memcpy 到 int 导致高位垃圾数据
            memcpy(&us0, ptr + reader._pos, 2)
            memcpy(&us1, ptr + reader._pos + 2, 2)
            memcpy(&us2, ptr + reader._pos + 4, 2)
            reader._pos += 6
            faces[i] = [us0, us1, us2]
    else: # 4 bytes
        for i in range(face_count):
            memcpy(&v0, ptr + reader._pos, 4)
            memcpy(&v1, ptr + reader._pos + 4, 4)
            memcpy(&v2, ptr + reader._pos + 8, 4)
            reader._pos += 12
            faces[i] = [v0, v1, v2]

    return faces


cdef list _parse_textures_cython(FastPmxReader reader, bint more_info):
    """解析纹理列表 (Cython优化)"""
    cdef unsigned int texture_count = reader.read_uint()
    cdef list textures = [None] * texture_count

    if more_info:
        print(f"解析 {texture_count} 个纹理...")

    cdef unsigned int i
    
    for i in range(texture_count):
        textures[i] = reader.read_variable_string()

    return textures


cdef list _parse_materials_cython(FastPmxReader reader, list textures, bint more_info):
    """解析材质数据 (Cython优化)"""
    cdef unsigned int material_count = reader.read_uint()
    cdef list materials = [None] * material_count

    if more_info:
        print(f"解析 {material_count} 个材质...")

    cdef unsigned int i, j
    cdef str name_jp, name_en, texture_path, sphere_path, toon_path, comment
    cdef float diff_r, diff_g, diff_b, diff_a
    cdef float spec_r, spec_g, spec_b, spec_strength
    cdef float amb_r, amb_g, amb_b
    cdef unsigned char flag_byte, sphere_mode_val, toon_flag, toon_index_builtin
    cdef float edge_r, edge_g, edge_b, edge_a, edge_size
    cdef int tex_index, sphere_index, toon_index
    cdef unsigned int face_count
    cdef list flags_list
    cdef int texture_count = len(textures)
    
    cdef int texture_index_size = reader._texture_index_size

    for i in range(material_count):
        # 材质名称
        name_jp = reader.read_variable_string()
        name_en = reader.read_variable_string()

        # 漫反射颜色
        memcpy(&diff_r, reader._ptr + reader._pos, 4)
        memcpy(&diff_g, reader._ptr + reader._pos + 4, 4)
        memcpy(&diff_b, reader._ptr + reader._pos + 8, 4)
        memcpy(&diff_a, reader._ptr + reader._pos + 12, 4)
        reader._pos += 16

        # 镜面反射颜色
        memcpy(&spec_r, reader._ptr + reader._pos, 4)
        memcpy(&spec_g, reader._ptr + reader._pos + 4, 4)
        memcpy(&spec_b, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 镜面反射强度
        memcpy(&spec_strength, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 环境光颜色
        memcpy(&amb_r, reader._ptr + reader._pos, 4)
        memcpy(&amb_g, reader._ptr + reader._pos + 4, 4)
        memcpy(&amb_b, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 材质标志
        flag_byte = reader._ptr[reader._pos]
        reader._pos += 1
        flags_list = [(flag_byte >> j) & 1 == 1 for j in range(8)]

        # 边缘颜色和大小
        memcpy(&edge_r, reader._ptr + reader._pos, 4)
        memcpy(&edge_g, reader._ptr + reader._pos + 4, 4)
        memcpy(&edge_b, reader._ptr + reader._pos + 8, 4)
        memcpy(&edge_a, reader._ptr + reader._pos + 12, 4)
        reader._pos += 16

        memcpy(&edge_size, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 纹理索引 (直接内联读取逻辑)
        if texture_index_size == 1:
            tex_index = <signed char>reader._ptr[reader._pos]
            reader._pos += 1
        elif texture_index_size == 2:
            tex_index = reader.read_short()
        else:
            tex_index = reader.read_int()

        if 0 <= tex_index < texture_count:
            texture_path = textures[tex_index]
        else:
            texture_path = ""

        # 球面纹理索引
        if texture_index_size == 1:
            sphere_index = <signed char>reader._ptr[reader._pos]
            reader._pos += 1
        elif texture_index_size == 2:
            sphere_index = reader.read_short()
        else:
            sphere_index = reader.read_int()

        if 0 <= sphere_index < texture_count:
            sphere_path = textures[sphere_index]
        else:
            sphere_path = ""

        # 球面纹理模式
        sphere_mode_val = reader._ptr[reader._pos]
        reader._pos += 1

        # Toon渲染
        toon_flag = reader._ptr[reader._pos]
        reader._pos += 1
        
        if toon_flag == 0:
            # 使用内置Toon纹理
            toon_index_builtin = reader._ptr[reader._pos]
            reader._pos += 1
            toon_path = f"toon{toon_index_builtin:02d}.bmp"
        else:
            # 使用自定义Toon纹理
            if texture_index_size == 1:
                toon_index = <signed char>reader._ptr[reader._pos]
                reader._pos += 1
            elif texture_index_size == 2:
                toon_index = reader.read_short()
            else:
                toon_index = reader.read_int()

            if 0 <= toon_index < texture_count:
                toon_path = textures[toon_index]
            else:
                toon_path = ""

        # 注释和面数
        comment = reader.read_variable_string()
        face_count = reader.read_uint()

        # 创建材质对象 (尽量减少中间列表变量)
        materials[i] = PmxMaterial(
            name_jp=name_jp,
            name_en=name_en,
            diffuse_color=[diff_r, diff_g, diff_b, diff_a],
            specular_color=[spec_r, spec_g, spec_b],
            specular_strength=spec_strength,
            ambient_color=[amb_r, amb_g, amb_b],
            flags=MaterialFlags(flags_list),
            edge_color=[edge_r, edge_g, edge_b, edge_a],
            edge_size=edge_size,
            texture_path=texture_path,
            sphere_path=sphere_path,
            sphere_mode=SphMode(sphere_mode_val),
            toon_path=toon_path,
            comment=comment,
            face_count=face_count
        )

    return materials
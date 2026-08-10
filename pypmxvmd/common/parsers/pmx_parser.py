"""
PyPMXVMD PMX解析器

负责解析和写入PMX格式文件。
当前 binary reader 完整消费受支持的 PMX 2.0/2.1 section。
"""

import struct
from pathlib import Path
from typing import List, Optional, Union

from pypmxvmd.common.io.binary_io import BinaryIOHandler
from pypmxvmd.common.models.pmx import (
    BoneFlags,
    JointType,
    MaterialFlags,
    MorphMaterialOperation,
    MorphPanel,
    MorphType,
    PmxBone,
    PmxBoneIkLink,
    PmxFrame,
    PmxFrameItem,
    PmxHeader,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemFlip,
    PmxMorphItemGroup,
    PmxMorphItemImpulse,
    PmxMorphItemMaterial,
    PmxMorphItemUv,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxSoftBody,
    PmxSoftBodyAnchor,
    PmxSoftBodyCluster,
    PmxSoftBodyConfig,
    PmxSoftBodyIteration,
    PmxSoftBodyMaterial,
    PmxVertex,
    RigidBodyPhysMode,
    RigidBodyShape,
    SoftBodyAeroModel,
    SoftBodyFlags,
    SoftBodyShape,
    SphMode,
    WeightMode,
)
from pypmxvmd.common.parsers.pmx_parser_nuthouse import PmxParserNuthouse
from pypmxvmd.common.pmx.cursor import PmxByteSpan, PmxCursor
from pypmxvmd.common.pmx.document import BinarySpan, PmxDocument
from pypmxvmd.common.pmx.errors import (
    IncompletePmxError,
    IncompletePmxWriterError,
    PmxFormatError,
    UnsupportedPmxFeatureError,
)
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.report import PmxParseReport, PmxParseResult, PmxSectionReport

# 尝试导入Cython优化模块
try:
    from pypmxvmd.common.parsers._fast_pmx import parse_pmx_cython

    _CYTHON_AVAILABLE = True
except ImportError:
    _CYTHON_AVAILABLE = False


class PmxParser:
    """PMX文件解析器

    当前提供 strict/partial 读取、完整性报告和 canonical PMX 2.0/2.1 写入。
    PMX 2.x 可选字段级 source span。
    """

    def __init__(self, limits: PmxLimits = DEFAULT_PMX_LIMITS):
        """初始化PMX解析器"""
        self._io_handler = BinaryIOHandler("utf-16le")  # PMX默认使用UTF-16LE
        self._limits = limits
        self._cursor: Optional[PmxCursor] = None
        self._use_utf8 = False  # 编码标志
        self._version = 2.0
        self._progress_callback = None
        self._last_parse_report: Optional[PmxParseReport] = None
        self._last_field_spans: tuple[BinarySpan, ...] = ()
        self._last_record_spans: tuple[PmxByteSpan, ...] = ()

        # 索引类型格式字符串
        self._vertex_index_format = "B"  # 顶点索引格式
        self._texture_index_format = "b"  # 纹理索引格式
        self._material_index_format = "b"  # 材质索引格式
        self._bone_index_format = "b"  # 骨骼索引格式
        self._morph_index_format = "b"  # 变形索引格式
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

    @property
    def last_parse_report(self) -> Optional[PmxParseReport]:
        """Return the most recent parse report produced by this parser."""
        return self._last_parse_report

    @property
    def last_field_spans(self) -> tuple[BinarySpan, ...]:
        """Return fixed-width field spans from the most recent tracked parse."""
        return self._last_field_spans

    @property
    def last_record_spans(self) -> tuple[PmxByteSpan, ...]:
        """Return variable-width record spans from the most recent tracked parse."""
        return self._last_record_spans

    def parse_file(
        self,
        file_path: Union[str, Path],
        more_info: bool = False,
        *,
        implementation: str = "auto",
        strict_eof: bool = True,
        track_spans: bool = False,
    ) -> PmxModel:
        """Parse a complete PMX file or fail closed.

        PMX 2.0 is consumed through Joint; PMX 2.1 additionally consumes the
        Soft Body section. Both versions must end exactly at EOF.

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息
            implementation: auto、python、fast 或 cython
            strict_eof: 完整读取固定为 True；诊断读取使用 parse_file_partial
            track_spans: 返回模型并保存字段级及已支持的 record span

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            IncompletePmxError: 当前实现没有加载全部必需 section
            ValueError: 文件格式错误
        """
        if type(strict_eof) is not bool:
            raise ValueError("strict_eof must be a bool")
        if not strict_eof:
            raise ValueError(
                "parse_file() is always strict; use parse_file_partial() "
                "for diagnostic incomplete results"
            )
        if type(track_spans) is not bool:
            raise ValueError("track_spans must be a bool")
        result = self.parse_file_partial(
            file_path,
            more_info=more_info,
            implementation=implementation,
            track_spans=track_spans,
        )
        if not result.report.is_complete:
            raise IncompletePmxError(result.report)
        return result.model

    def parse_file_partial(
        self,
        file_path: Union[str, Path],
        more_info: bool = False,
        implementation: str = "auto",
        *,
        track_spans: bool = False,
    ) -> PmxParseResult:
        """Explicitly parse the sections supported by a selected implementation.

        The returned report makes the loaded sections, final byte offset and
        missing mandatory sections observable.  A partial result must not be
        passed to a complete PMX writer.
        """
        if type(track_spans) is not bool:
            raise ValueError("track_spans must be a bool")
        if not isinstance(implementation, str):
            raise ValueError("PMX implementation must be a string")
        self._last_field_spans = ()
        self._last_record_spans = ()
        file_path = Path(file_path)
        selected = implementation.lower()
        if selected == "auto":
            # The Cursor path is the fail-closed implementation.  Cython stays
            # explicitly selectable until its reader adopts the same limits
            # and diagnostics in W8.
            selected = "fast"

        if selected == "python":
            model = self._parse_file_python(
                file_path, more_info, track_spans=track_spans
            )
        elif selected == "fast":
            model = self.parse_file_fast(file_path, more_info, track_spans=track_spans)
        elif selected == "cython":
            if not _CYTHON_AVAILABLE:
                raise RuntimeError(
                    "Cython PMX parser is not available; choose 'fast' or 'python'"
                )
            # Validate every byte range understood by the current Cython ABI
            # before entering code compiled with disabled bounds checks.
            probe = PmxParser(limits=self._limits)
            probe_model = probe.parse_file_fast(
                file_path, more_info=False, track_spans=track_spans
            )
            probe_report = probe.last_parse_report
            if probe_report is None:
                raise RuntimeError("Fast PMX parser did not produce a parse report")
            # Execute the extension only after the safe probe.  Its current ABI
            # still omits semantic fields such as additional UV/SDEF and all
            # post-Material sections, so correctness requires returning the
            # canonical Cursor model until W8 reaches full field parity.
            if probe_model.header.version < 2.1:
                parse_pmx_cython(file_path.read_bytes(), more_info)
            model = probe_model

            # The current Cython ABI returns only a model.  Reuse the safe
            # cursor probe's section boundary until W8 adds a native report.
            self._last_parse_report = PmxParseReport(
                implementation="cython",
                version=model.header.version,
                file_size=probe_report.file_size,
                final_offset=probe_report.final_offset,
                sections=probe_report.sections,
            )
            self._last_field_spans = probe.last_field_spans
            self._last_record_spans = probe.last_record_spans
            model.parse_report = self._last_parse_report
        else:
            raise ValueError(
                "Unknown PMX implementation: "
                f"{implementation!r}; expected auto, python, fast, or cython"
            )

        report = self._last_parse_report
        if report is None:
            raise RuntimeError("PMX parser did not produce a parse report")
        return PmxParseResult(
            model=model,
            report=report,
            field_spans=self._last_field_spans,
            record_spans=self._last_record_spans,
        )

    def _parse_file_python(
        self,
        file_path: Union[str, Path],
        more_info: bool = False,
        *,
        track_spans: bool = False,
    ) -> PmxModel:
        """Parse supported PMX sections through the safe Python Cursor."""
        return self._parse_file_cursor(
            file_path,
            more_info,
            implementation="python",
            track_spans=track_spans,
        )

    def parse_file_fast(
        self,
        file_path: Union[str, Path],
        more_info: bool = False,
        *,
        track_spans: bool = False,
    ) -> PmxModel:
        """Parse supported PMX sections through the bounds-checked Cursor."""
        return self._parse_file_cursor(
            file_path,
            more_info,
            implementation="fast",
            track_spans=track_spans,
        )

    def _parse_file_cursor(
        self,
        file_path: Union[str, Path],
        more_info: bool,
        *,
        implementation: str,
        track_spans: bool = False,
    ) -> PmxModel:
        """Shared Cursor-backed reader for the current Python implementations."""
        file_path = Path(file_path)
        if more_info:
            print(f"开始解析PMX文件: {file_path}")

        cursor = PmxCursor(
            file_path.read_bytes(),
            limits=self._limits,
            track_fields=track_spans,
        )
        self._cursor = cursor
        pmx_model = PmxModel()
        sections: List[PmxSectionReport] = []
        current_section = "header"

        try:
            start = cursor.position
            with cursor.span("header"):
                pmx_model.header = self._parse_header_fast()
            sections.append(PmxSectionReport("header", start, cursor.position, 1))

            current_section = "vertices"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.vertices = self._parse_vertices_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.vertices)
                )
            )

            current_section = "faces"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.faces = self._parse_faces_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.faces)
                )
            )

            current_section = "textures"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.textures = self._parse_textures_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.textures)
                )
            )

            current_section = "materials"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.materials = self._parse_materials_fast(
                    more_info, pmx_model.textures
                )
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.materials)
                )
            )

            current_section = "bones"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.bones = self._parse_bones_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.bones)
                )
            )

            current_section = "morphs"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.morphs = self._parse_morphs_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.morphs)
                )
            )

            current_section = "display_frames"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.frames = self._parse_display_frames_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.frames)
                )
            )

            current_section = "rigid_bodies"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.rigidbodies = self._parse_rigid_bodies_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section,
                    start,
                    cursor.position,
                    len(pmx_model.rigidbodies),
                )
            )

            current_section = "joints"
            start = cursor.position
            with cursor.span(current_section):
                pmx_model.joints = self._parse_joints_fast(more_info)
            sections.append(
                PmxSectionReport(
                    current_section, start, cursor.position, len(pmx_model.joints)
                )
            )

            if pmx_model.header.version >= 2.1:
                current_section = "soft_bodies"
                start = cursor.position
                with cursor.span(current_section):
                    pmx_model.softbodies = self._parse_soft_bodies_fast(more_info)
                sections.append(
                    PmxSectionReport(
                        current_section,
                        start,
                        cursor.position,
                        len(pmx_model.softbodies),
                    )
                )
            self._last_parse_report = PmxParseReport(
                implementation=implementation,
                version=pmx_model.header.version,
                file_size=cursor.size,
                final_offset=cursor.position,
                sections=tuple(sections),
            )
            self._last_field_spans = cursor.field_spans
            self._last_record_spans = cursor.record_spans
            pmx_model.parse_report = self._last_parse_report

            if more_info:
                print(
                    f"PMX解析完成: {len(pmx_model.vertices)}个顶点, "
                    f"{len(pmx_model.faces)}个面, "
                    f"{len(pmx_model.materials)}个材质, "
                    f"{len(pmx_model.bones)}个骨骼, "
                    f"{len(pmx_model.morphs)}个Morph, "
                    f"{len(pmx_model.rigidbodies)}个刚体, "
                    f"{len(pmx_model.joints)}个Joint, "
                    f"{len(pmx_model.softbodies)}个Soft Body"
                )
            return pmx_model
        except Exception as exc:
            offset = cursor.position
            version = getattr(pmx_model.header, "version", 0.0)
            self._last_parse_report = PmxParseReport(
                implementation=implementation,
                version=version,
                file_size=cursor.size,
                final_offset=offset,
                sections=tuple(sections),
                failed_section=current_section,
                failed_offset=offset,
            )
            self._last_field_spans = cursor.field_spans
            self._last_record_spans = cursor.record_spans
            if isinstance(exc, PmxFormatError):
                exc.report = self._last_parse_report
                raise
            raise PmxFormatError(
                f"PMX parsing failed: {exc}",
                section=current_section,
                offset=offset,
                report=self._last_parse_report,
            ) from exc

    def parse_file_cython(
        self, file_path: Union[str, Path], more_info: bool = False
    ) -> PmxModel:
        """Explicitly parse the currently supported sections with Cython.

        If the extension is unavailable this method uses the fast Python
        implementation.  Parse errors are never swallowed or routed through an
        unrelated fallback parser.

        Args:
            file_path: PMX文件路径
            more_info: 是否显示更多解析信息

        Returns:
            解析后的PMX模型对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误
        """
        implementation = "cython" if _CYTHON_AVAILABLE else "fast"
        return self.parse_file_partial(
            file_path,
            more_info=more_info,
            implementation=implementation,
        ).model

    def _parse_file_nuthouse(
        self, file_path: Union[str, Path], more_info: bool = False
    ) -> PmxModel:
        """使用Nuthouse实现解析PMX文件（保守回退）"""
        parser = PmxParserNuthouse(self._progress_callback)
        return parser.parse_file(file_path, more_info=more_info)

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
            comment_en=comment_en,
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
            4: "I",  # unsigned int
        }

        non_vertex_formats = {
            1: "b",  # signed byte
            2: "h",  # signed short
            4: "i",  # signed int
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

    def _require_cursor(self) -> PmxCursor:
        if self._cursor is None:
            raise RuntimeError("PMX Cursor is not initialized")
        return self._cursor

    def _parse_header_fast(self) -> PmxHeader:
        """Parse and validate the PMX header through the active Cursor."""
        cursor = self._require_cursor()
        magic = cursor.read_exact(4)
        if magic != b"PMX ":
            raise PmxFormatError(
                f"Invalid PMX magic {magic!r}; expected b'PMX '",
                section=cursor.section,
                offset=0,
            )

        version = round(float(cursor.unpack("<f")[0]), 5)
        if version not in (2.0, 2.1):
            raise PmxFormatError(
                f"Unsupported PMX version {version}",
                section=cursor.section,
                offset=4,
            )
        self._version = version

        global_flag_count = int(cursor.unpack("<B")[0])
        if global_flag_count != 8:
            raise PmxFormatError(
                f"Invalid PMX global flag count {global_flag_count}; expected 8",
                section=cursor.section,
                offset=8,
            )

        global_flags = tuple(int(value) for value in cursor.unpack("<8B"))
        self._apply_global_flags(global_flags)

        text_encoding = global_flags[0]
        if text_encoding == 0:
            self._use_utf8 = False
            encoding = "utf-16le"
        elif text_encoding == 1:
            self._use_utf8 = True
            encoding = "utf-8"
        else:
            raise PmxFormatError(
                f"Invalid PMX text encoding flag {text_encoding}",
                section=cursor.section,
                offset=9,
            )

        name_jp = cursor.read_string(encoding)
        name_en = cursor.read_string(encoding)
        comment_jp = cursor.read_string(encoding)
        comment_en = cursor.read_string(encoding)

        return PmxHeader(
            version=version,
            name_jp=name_jp,
            name_en=name_en,
            comment_jp=comment_jp,
            comment_en=comment_en,
            encoding=text_encoding,
            additional_uv_count=global_flags[1],
            vertex_index_size=global_flags[2],
            texture_index_size=global_flags[3],
            material_index_size=global_flags[4],
            bone_index_size=global_flags[5],
            morph_index_size=global_flags[6],
            rigid_body_index_size=global_flags[7],
            global_flags=bytes(global_flags),
        )

    def _apply_global_flags(self, global_flags: tuple[int, ...]) -> None:
        """Validate and cache PMX header layout parameters."""
        cursor = self._require_cursor()
        additional_uv_count = global_flags[1]
        if not 0 <= additional_uv_count <= 4:
            raise PmxFormatError(
                f"Invalid PMX additional UV count {additional_uv_count}; expected 0..4",
                section=cursor.section,
                offset=10,
            )

        index_names = (
            "vertex",
            "texture",
            "material",
            "bone",
            "morph",
            "rigid body",
        )
        index_sizes = global_flags[2:8]
        for offset, (name, size) in enumerate(zip(index_names, index_sizes), start=11):
            if size not in (1, 2, 4):
                raise PmxFormatError(
                    f"Invalid PMX {name} index size {size}; expected 1, 2, or 4",
                    section=cursor.section,
                    offset=offset,
                )

        self._additional_uv_count = additional_uv_count
        (
            self._vertex_index_size,
            self._texture_index_size,
            self._material_index_size,
            self._bone_index_size,
            self._morph_index_size,
            self._rigidbody_index_size,
        ) = index_sizes

        unsigned_formats = {1: "B", 2: "H", 4: "I"}
        signed_formats = {1: "b", 2: "h", 4: "i"}
        self._vertex_index_format = unsigned_formats[self._vertex_index_size]
        self._texture_index_format = signed_formats[self._texture_index_size]
        self._material_index_format = signed_formats[self._material_index_size]
        self._bone_index_format = signed_formats[self._bone_index_size]
        self._morph_index_format = signed_formats[self._morph_index_size]
        self._rigidbody_index_format = signed_formats[self._rigidbody_index_size]

    def _parse_vertices_fast(self, more_info: bool) -> List[PmxVertex]:
        """Parse the currently modeled vertex fields through the Cursor."""
        cursor = self._require_cursor()
        vertex_count = cursor.read_count("vertex count")
        vertices = []

        if more_info:
            print(f"解析 {vertex_count} 个顶点...")

        # 获取附加UV数量（默认为0）
        additional_uv_count = getattr(self, "_additional_uv_count", 0)

        for i in range(vertex_count):
            # 报告进度
            if i % 1000 == 0:
                self._report_progress(i, vertex_count)
            record_start = cursor.position

            # 基础顶点数据
            pos_x, pos_y, pos_z = cursor.unpack("<3f")
            norm_x, norm_y, norm_z = cursor.unpack("<3f")
            uv_u, uv_v = cursor.unpack("<2f")

            additional_uvs = [
                list(cursor.unpack("<4f")) for _ in range(additional_uv_count)
            ]

            # 权重模式
            weight_mode_offset = cursor.position
            weight_mode_value = int(cursor.unpack("<B")[0])
            try:
                weight_mode = WeightMode(weight_mode_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX vertex weight mode {weight_mode_value}",
                    section=cursor.section,
                    offset=weight_mode_offset,
                ) from exc
            if weight_mode == WeightMode.QDEF and self._version < 2.1:
                raise PmxFormatError(
                    "QDEF requires PMX 2.1",
                    section=cursor.section,
                    offset=weight_mode_offset,
                )

            # 权重数据
            weight_data = []
            sdef_c = None
            sdef_r0 = None
            sdef_r1 = None
            if weight_mode == WeightMode.BDEF1:
                bone_idx = cursor.read_index(self._bone_index_size)
                weight_data = [[bone_idx, 1.0]]
            elif weight_mode == WeightMode.BDEF2:
                bone1_idx = cursor.read_index(self._bone_index_size)
                bone2_idx = cursor.read_index(self._bone_index_size)
                bone1_weight = float(cursor.unpack("<f")[0])
                weight_data = [
                    [bone1_idx, bone1_weight],
                    [bone2_idx, 1.0 - bone1_weight],
                ]
            elif weight_mode == WeightMode.BDEF4:
                bone_indices = [
                    cursor.read_index(self._bone_index_size) for _ in range(4)
                ]
                bone_weights = cursor.unpack("<4f")
                weight_data = list(zip(bone_indices, bone_weights))
            elif weight_mode == WeightMode.SDEF:
                bone1_idx = cursor.read_index(self._bone_index_size)
                bone2_idx = cursor.read_index(self._bone_index_size)
                bone1_weight = float(cursor.unpack("<f")[0])
                sdef_c = list(cursor.unpack("<3f"))
                sdef_r0 = list(cursor.unpack("<3f"))
                sdef_r1 = list(cursor.unpack("<3f"))
                weight_data = [
                    [bone1_idx, bone1_weight],
                    [bone2_idx, 1.0 - bone1_weight],
                ]
            elif weight_mode == WeightMode.QDEF:
                # QDEF模式：类似BDEF4
                bone_indices = [
                    cursor.read_index(self._bone_index_size) for _ in range(4)
                ]
                bone_weights = cursor.unpack("<4f")
                weight_data = list(zip(bone_indices, bone_weights))

            # 边缘倍率
            edge_scale = float(cursor.unpack("<f")[0])

            # 创建顶点对象
            vertex = PmxVertex(
                position=[pos_x, pos_y, pos_z],
                normal=[norm_x, norm_y, norm_z],
                uv=[uv_u, uv_v],
                additional_uvs=additional_uvs,
                weight_mode=weight_mode,
                weight=weight_data,
                edge_scale=edge_scale,
                sdef_c=sdef_c,
                sdef_r0=sdef_r0,
                sdef_r1=sdef_r1,
            )

            vertices.append(vertex)
            cursor.mark_record(f"vertices[{i}]", record_start)

        self._report_progress(vertex_count, vertex_count)
        return vertices

    def _parse_faces_fast(self, more_info: bool) -> List[List[int]]:
        """Parse triangle vertex indices through the Cursor."""
        cursor = self._require_cursor()
        # 读取面数量（实际是索引数量）
        count_offset = cursor.position
        index_count = cursor.read_count("face vertex index count")
        if index_count % 3:
            raise PmxFormatError(
                f"PMX face vertex index count {index_count} is not divisible by 3",
                section=cursor.section,
                offset=count_offset,
            )
        face_count = index_count // 3

        if more_info:
            print(f"解析 {face_count} 个面...")

        faces = []

        for i in range(face_count):
            if i % 1000 == 0:
                self._report_progress(i, face_count)
            record_start = cursor.position

            indices = [
                cursor.read_index(self._vertex_index_size, signed=False)
                for _ in range(3)
            ]
            faces.append(indices)
            cursor.mark_record(f"faces[{i}]", record_start)

        self._report_progress(face_count, face_count)
        return faces

    def _parse_textures_fast(self, more_info: bool) -> List[str]:
        """Parse texture strings through the Cursor."""
        cursor = self._require_cursor()
        texture_count = cursor.read_count("texture count")
        textures = []

        if more_info:
            print(f"解析 {texture_count} 个纹理...")

        for i in range(texture_count):
            texture_path = cursor.read_string("utf-8" if self._use_utf8 else "utf-16le")
            textures.append(texture_path)

        return textures

    def _parse_materials_fast(
        self, more_info: bool, textures: List[str]
    ) -> List[PmxMaterial]:
        """Parse the currently modeled material fields through the Cursor."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        # 读取材质数量
        material_count = cursor.read_count("material count")
        materials = []

        if more_info:
            print(f"解析 {material_count} 个材质...")

        for i in range(material_count):
            self._report_progress(i, material_count)
            record_start = cursor.position

            # 材质名称
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)

            # 颜色数据
            prefix = f"materials[{i}]"
            diffuse_color = list(
                cursor.unpack_field(f"{prefix}.diffuse_color", "<4f", "float_vector")
            )
            specular_color = list(
                cursor.unpack_field(f"{prefix}.specular_color", "<3f", "float_vector")
            )
            specular_strength = float(
                cursor.unpack_field(f"{prefix}.specular_strength", "<f", "float")[0]
            )
            ambient_color = list(
                cursor.unpack_field(f"{prefix}.ambient_color", "<3f", "float_vector")
            )

            # 标志位
            flag_byte = int(cursor.unpack_field(f"{prefix}.flags", "<B", "flags")[0])
            flags_list = [(flag_byte >> j) & 1 == 1 for j in range(8)]
            flags = MaterialFlags(flags_list)

            # 边缘数据
            edge_color = list(
                cursor.unpack_field(f"{prefix}.edge_color", "<4f", "float_vector")
            )
            edge_size = float(
                cursor.unpack_field(f"{prefix}.edge_size", "<f", "float")[0]
            )

            # 纹理索引
            tex_index = cursor.read_index(self._texture_index_size)
            texture_path = textures[tex_index] if 0 <= tex_index < len(textures) else ""

            # 球面纹理索引
            sphere_index = cursor.read_index(self._texture_index_size)
            sphere_path = (
                textures[sphere_index] if 0 <= sphere_index < len(textures) else ""
            )
            sphere_mode = SphMode(
                int(cursor.unpack_field(f"{prefix}.sphere_mode", "<B", "enum")[0])
            )

            # 卡通渲染
            toon_flag_offset = cursor.position
            toon_flag = int(cursor.unpack("<B")[0])
            if toon_flag == 0:
                # 使用独立的纹理表索引
                toon_index = cursor.read_index(self._texture_index_size)
                toon_path = (
                    textures[toon_index] if 0 <= toon_index < len(textures) else ""
                )
            elif toon_flag == 1:
                # 使用内置共享 Toon（toon01.bmp 至 toon10.bmp）
                toon_index = int(cursor.unpack("<B")[0])
                if toon_index > 9:
                    raise PmxFormatError(
                        f"Invalid shared Toon texture index {toon_index}; expected 0..9",
                        section=cursor.section,
                        offset=cursor.position - 1,
                    )
                toon_path = f"toon{toon_index + 1:02d}.bmp"
            else:
                raise PmxFormatError(
                    f"Invalid PMX Toon sharing flag {toon_flag}; expected 0 or 1",
                    section=cursor.section,
                    offset=toon_flag_offset,
                )

            # 注释和面数
            comment = cursor.read_string(encoding)
            face_count = cursor.read_count("material face vertex count")

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
                texture_index=tex_index,
                sphere_path=sphere_path,
                sphere_texture_index=sphere_index,
                sphere_mode=sphere_mode,
                toon_path=toon_path,
                toon_sharing=toon_flag,
                toon_texture_index=toon_index,
                comment=comment,
                face_count=face_count,
            )

            materials.append(material)
            cursor.mark_record(prefix, record_start)

        self._report_progress(material_count, material_count)
        return materials

    def _parse_bones_fast(self, more_info: bool) -> List[PmxBone]:
        """Parse every PMX 2.x bone flag and its conditional payload."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        bone_count = cursor.read_count("bone count")
        bones: List[PmxBone] = []

        if more_info:
            print(f"解析 {bone_count} 个骨骼...")

        for index in range(bone_count):
            self._report_progress(index, bone_count)
            record_start = cursor.position

            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)
            prefix = f"bones[{index}]"
            position = list(
                cursor.unpack_field(f"{prefix}.position", "<3f", "float_vector")
            )
            parent_index = cursor.read_index_field(
                f"{prefix}.parent_index", self._bone_index_size
            )
            deform_layer = int(
                cursor.unpack_field(f"{prefix}.deform_layer", "<i", "int")[0]
            )
            bone_flags = BoneFlags(value=int(cursor.unpack("<H")[0]))

            if bone_flags.tail_usebonelink:
                tail: Union[int, List[float]] = cursor.read_index_field(
                    f"{prefix}.tail", self._bone_index_size
                )
            else:
                tail = list(
                    cursor.unpack_field(f"{prefix}.tail", "<3f", "float_vector")
                )

            inherit_parent_index = None
            inherit_ratio = None
            if bone_flags.inherit_rot or bone_flags.inherit_trans:
                inherit_parent_index = cursor.read_index_field(
                    f"{prefix}.inherit_parent_index", self._bone_index_size
                )
                inherit_ratio = float(
                    cursor.unpack_field(f"{prefix}.inherit_ratio", "<f", "float")[0]
                )

            fixed_axis = None
            if bone_flags.has_fixedaxis:
                fixed_axis = list(
                    cursor.unpack_field(f"{prefix}.fixed_axis", "<3f", "float_vector")
                )

            local_axis_x = None
            local_axis_z = None
            if bone_flags.has_localaxis:
                local_axis_x = list(
                    cursor.unpack_field(f"{prefix}.local_axis_x", "<3f", "float_vector")
                )
                local_axis_z = list(
                    cursor.unpack_field(f"{prefix}.local_axis_z", "<3f", "float_vector")
                )

            external_parent_index = None
            if bone_flags.has_external_parent:
                external_parent_index = int(
                    cursor.unpack_field(f"{prefix}.external_parent_index", "<i", "int")[
                        0
                    ]
                )

            ik_target_index = None
            ik_loop_count = None
            ik_angle_limit = None
            ik_links: List[PmxBoneIkLink] = []
            if bone_flags.ik:
                ik_target_index = cursor.read_index_field(
                    f"{prefix}.ik_target_index", self._bone_index_size
                )
                ik_loop_count = cursor.read_count_field(
                    f"{prefix}.ik_loop_count", "IK loop count"
                )
                ik_angle_limit = float(
                    cursor.unpack_field(f"{prefix}.ik_angle_limit", "<f", "float")[0]
                )
                ik_link_count = cursor.read_count("IK link count")

                for link_index in range(ik_link_count):
                    link_prefix = f"{prefix}.ik_links[{link_index}]"
                    link_bone_index = cursor.read_index_field(
                        f"{link_prefix}.bone_index", self._bone_index_size
                    )
                    limit_flag_offset = cursor.position
                    limit_flag = int(cursor.unpack("<B")[0])
                    if limit_flag not in (0, 1):
                        raise PmxFormatError(
                            "Invalid PMX IK link angle-limit flag "
                            f"{limit_flag}; expected 0 or 1",
                            section=cursor.section,
                            offset=limit_flag_offset,
                        )

                    limit_min = None
                    limit_max = None
                    if limit_flag == 1:
                        limit_min = list(
                            cursor.unpack_field(
                                f"{link_prefix}.limit_min",
                                "<3f",
                                "float_vector",
                            )
                        )
                        limit_max = list(
                            cursor.unpack_field(
                                f"{link_prefix}.limit_max",
                                "<3f",
                                "float_vector",
                            )
                        )

                    ik_links.append(
                        PmxBoneIkLink(
                            bone_index=link_bone_index,
                            limit_min=limit_min,
                            limit_max=limit_max,
                            has_limits=bool(limit_flag),
                        )
                    )

            bones.append(
                PmxBone(
                    name_jp=name_jp,
                    name_en=name_en,
                    position=position,
                    parent_index=parent_index,
                    deform_layer=deform_layer,
                    bone_flags=bone_flags,
                    tail=tail,
                    inherit_parent_index=inherit_parent_index,
                    inherit_ratio=inherit_ratio,
                    fixed_axis=fixed_axis,
                    local_axis_x=local_axis_x,
                    local_axis_z=local_axis_z,
                    external_parent_index=external_parent_index,
                    ik_target_index=ik_target_index,
                    ik_loop_count=ik_loop_count,
                    ik_angle_limit=ik_angle_limit,
                    ik_links=ik_links,
                )
            )
            cursor.mark_record(prefix, record_start)

        self._report_progress(bone_count, bone_count)
        return bones

    def _parse_morphs_fast(self, more_info: bool) -> List[PmxMorph]:
        """Parse every version-appropriate PMX morph without lossy conversion."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        morph_count = cursor.read_count("morph count")
        morphs: List[PmxMorph] = []

        if more_info:
            print(f"解析 {morph_count} 个Morph...")

        for index in range(morph_count):
            self._report_progress(index, morph_count)
            record_start = cursor.position
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)

            panel_offset = cursor.position
            panel_value = int(cursor.unpack("<B")[0])
            try:
                panel = MorphPanel(panel_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX morph panel {panel_value}; expected 0..4",
                    section=cursor.section,
                    offset=panel_offset,
                ) from exc

            type_offset = cursor.position
            morph_type_value = int(cursor.unpack("<B")[0])
            try:
                morph_type = MorphType(morph_type_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX morph type {morph_type_value}",
                    section=cursor.section,
                    offset=type_offset,
                ) from exc
            if self._version < 2.1 and morph_type in (
                MorphType.FLIP,
                MorphType.IMPULSE,
            ):
                raise PmxFormatError(
                    f"PMX 2.1 morph type {morph_type.name} in PMX 2.0",
                    section=cursor.section,
                    offset=type_offset,
                )

            item_count = cursor.read_count("morph item count")
            items: List[object] = []
            for _ in range(item_count):
                if morph_type == MorphType.GROUP:
                    items.append(
                        PmxMorphItemGroup(
                            morph_index=cursor.read_index(self._morph_index_size),
                            value=float(cursor.unpack("<f")[0]),
                        )
                    )
                elif morph_type == MorphType.VERTEX:
                    items.append(
                        PmxMorphItemVertex(
                            vertex_index=cursor.read_index(
                                self._vertex_index_size, signed=False
                            ),
                            offset=list(cursor.unpack("<3f")),
                        )
                    )
                elif morph_type == MorphType.BONE:
                    items.append(
                        PmxMorphItemBone(
                            bone_index=cursor.read_index(self._bone_index_size),
                            translation=list(cursor.unpack("<3f")),
                            rotation=list(cursor.unpack("<4f")),
                        )
                    )
                elif morph_type in (
                    MorphType.UV,
                    MorphType.EXTENDED_UV1,
                    MorphType.EXTENDED_UV2,
                    MorphType.EXTENDED_UV3,
                    MorphType.EXTENDED_UV4,
                ):
                    items.append(
                        PmxMorphItemUv(
                            vertex_index=cursor.read_index(
                                self._vertex_index_size, signed=False
                            ),
                            offset=list(cursor.unpack("<4f")),
                        )
                    )
                elif morph_type == MorphType.MATERIAL:
                    material_index = cursor.read_index(self._material_index_size)
                    operation_offset = cursor.position
                    operation_value = int(cursor.unpack("<B")[0])
                    try:
                        operation = MorphMaterialOperation(operation_value)
                    except ValueError as exc:
                        raise PmxFormatError(
                            "Invalid PMX material morph operation "
                            f"{operation_value}; expected 0 or 1",
                            section=cursor.section,
                            offset=operation_offset,
                        ) from exc
                    items.append(
                        PmxMorphItemMaterial(
                            material_index=material_index,
                            operation=operation,
                            diffuse_color=list(cursor.unpack("<4f")),
                            specular_color=list(cursor.unpack("<3f")),
                            specular_strength=float(cursor.unpack("<f")[0]),
                            ambient_color=list(cursor.unpack("<3f")),
                            edge_color=list(cursor.unpack("<4f")),
                            edge_size=float(cursor.unpack("<f")[0]),
                            texture_tint=list(cursor.unpack("<4f")),
                            sphere_tint=list(cursor.unpack("<4f")),
                            toon_tint=list(cursor.unpack("<4f")),
                        )
                    )
                elif morph_type == MorphType.FLIP:
                    items.append(
                        PmxMorphItemFlip(
                            morph_index=cursor.read_index(self._morph_index_size),
                            value=float(cursor.unpack("<f")[0]),
                        )
                    )
                elif morph_type == MorphType.IMPULSE:
                    rigidbody_index = cursor.read_index(self._rigidbody_index_size)
                    local_offset = cursor.position
                    local_value = int(cursor.unpack("<B")[0])
                    if local_value not in (0, 1):
                        raise PmxFormatError(
                            f"Invalid PMX impulse local flag {local_value}",
                            section=cursor.section,
                            offset=local_offset,
                        )
                    items.append(
                        PmxMorphItemImpulse(
                            rigidbody_index=rigidbody_index,
                            is_local=bool(local_value),
                            velocity=list(cursor.unpack("<3f")),
                            torque=list(cursor.unpack("<3f")),
                        )
                    )
                else:  # pragma: no cover - enum cases above are exhaustive
                    raise AssertionError(f"Unhandled morph type: {morph_type}")

            morphs.append(
                PmxMorph(
                    name_jp=name_jp,
                    name_en=name_en,
                    panel=panel,
                    morph_type=morph_type,
                    items=items,
                )
            )
            cursor.mark_record(f"morphs[{index}]", record_start)

        self._report_progress(morph_count, morph_count)
        return morphs

    def _parse_display_frames_fast(self, more_info: bool) -> List[PmxFrame]:
        """Parse PMX display frames and typed Bone/Morph entries."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        frame_count = cursor.read_count("display frame count")
        frames: List[PmxFrame] = []

        if more_info:
            print(f"解析 {frame_count} 个表示枠...")

        for index in range(frame_count):
            self._report_progress(index, frame_count)
            record_start = cursor.position
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)
            special_offset = cursor.position
            special_value = int(cursor.unpack("<B")[0])
            if special_value not in (0, 1):
                raise PmxFormatError(
                    "Invalid PMX display-frame special flag "
                    f"{special_value}; expected 0 or 1",
                    section=cursor.section,
                    offset=special_offset,
                )

            item_count = cursor.read_count("display frame item count")
            items: List[PmxFrameItem] = []
            for _ in range(item_count):
                target_offset = cursor.position
                target = int(cursor.unpack("<B")[0])
                if target == 0:
                    item_index = cursor.read_index(self._bone_index_size)
                elif target == 1:
                    item_index = cursor.read_index(self._morph_index_size)
                else:
                    raise PmxFormatError(
                        "Invalid PMX display-frame item target "
                        f"{target}; expected 0 or 1",
                        section=cursor.section,
                        offset=target_offset,
                    )
                items.append(PmxFrameItem(is_morph=bool(target), index=item_index))

            frames.append(
                PmxFrame(
                    name_jp=name_jp,
                    name_en=name_en,
                    is_special=bool(special_value),
                    items=items,
                )
            )
            cursor.mark_record(f"display_frames[{index}]", record_start)

        self._report_progress(frame_count, frame_count)
        return frames

    def _parse_rigid_bodies_fast(self, more_info: bool) -> List[PmxRigidBody]:
        """Parse all PMX 2.0 rigid-body fields in their original units."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        rigid_body_count = cursor.read_count("rigid body count")
        rigid_bodies: List[PmxRigidBody] = []

        if more_info:
            print(f"解析 {rigid_body_count} 个刚体...")

        for index in range(rigid_body_count):
            self._report_progress(index, rigid_body_count)
            prefix = f"rigidbodies[{index}]"
            record_start = cursor.position
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)
            bone_index = cursor.read_index_field(
                f"{prefix}.bone_index", self._bone_index_size
            )

            group_offset = cursor.position
            collision_group = int(
                cursor.unpack_field(f"{prefix}.collision_group", "<B", "int")[0]
            )
            if collision_group > 15:
                raise PmxFormatError(
                    f"Invalid PMX rigid-body collision group {collision_group}",
                    section=cursor.section,
                    offset=group_offset,
                )
            collision_mask = int(
                cursor.unpack_field(f"{prefix}.collision_mask", "<H", "int")[0]
            )

            shape_offset = cursor.position
            shape_value = int(cursor.unpack_field(f"{prefix}.shape", "<B", "enum")[0])
            try:
                shape = RigidBodyShape(shape_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX rigid-body shape {shape_value}",
                    section=cursor.section,
                    offset=shape_offset,
                ) from exc

            size = list(cursor.unpack_field(f"{prefix}.size", "<3f", "float_vector"))
            position = list(
                cursor.unpack_field(f"{prefix}.position", "<3f", "float_vector")
            )
            rotation = list(
                cursor.unpack_field(f"{prefix}.rotation", "<3f", "float_vector")
            )
            mass = cursor.unpack_field(f"{prefix}.mass", "<f", "float")[0]
            move_damping = cursor.unpack_field(f"{prefix}.move_damping", "<f", "float")[
                0
            ]
            rotation_damping = cursor.unpack_field(
                f"{prefix}.rotation_damping", "<f", "float"
            )[0]
            repulsion = cursor.unpack_field(f"{prefix}.repulsion", "<f", "float")[0]
            friction = cursor.unpack_field(f"{prefix}.friction", "<f", "float")[0]

            mode_offset = cursor.position
            mode_value = int(
                cursor.unpack_field(f"{prefix}.physics_mode", "<B", "enum")[0]
            )
            try:
                physics_mode = RigidBodyPhysMode(mode_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX rigid-body physics mode {mode_value}",
                    section=cursor.section,
                    offset=mode_offset,
                ) from exc

            rigid_bodies.append(
                PmxRigidBody(
                    name_jp=name_jp,
                    name_en=name_en,
                    bone_index=bone_index,
                    collision_group=collision_group,
                    collision_mask=collision_mask,
                    shape=shape,
                    size=size,
                    position=position,
                    rotation=rotation,
                    physics_mode=physics_mode,
                    mass=float(mass),
                    move_damping=float(move_damping),
                    rotation_damping=float(rotation_damping),
                    repulsion=float(repulsion),
                    friction=float(friction),
                )
            )
            cursor.mark_record(prefix, record_start)

        self._report_progress(rigid_body_count, rigid_body_count)
        return rigid_bodies

    def _parse_joints_fast(self, more_info: bool) -> List[PmxJoint]:
        """Parse the six PMX Joint types in their shared raw layout."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        joint_count = cursor.read_count("joint count")
        joints: List[PmxJoint] = []

        if more_info:
            print(f"解析 {joint_count} 个Joint...")

        for index in range(joint_count):
            self._report_progress(index, joint_count)
            prefix = f"joints[{index}]"
            record_start = cursor.position
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)
            type_offset = cursor.position
            joint_type_value = int(
                cursor.unpack_field(f"{prefix}.joint_type", "<B", "enum")[0]
            )
            try:
                joint_type = JointType(joint_type_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Unsupported PMX joint type {joint_type_value}",
                    section=cursor.section,
                    offset=type_offset,
                ) from exc
            if self._version < 2.1 and joint_type != JointType.SPRING6DOF:
                raise PmxFormatError(
                    "Unsupported PMX joint type "
                    f"{joint_type_value}; PMX 2.0 requires Spring 6DOF (0)",
                    section=cursor.section,
                    offset=type_offset,
                )

            rigid_body_a_index = cursor.read_index_field(
                f"{prefix}.rigidbody1_index", self._rigidbody_index_size
            )
            rigid_body_b_index = cursor.read_index_field(
                f"{prefix}.rigidbody2_index", self._rigidbody_index_size
            )
            joints.append(
                PmxJoint(
                    name_jp=name_jp,
                    name_en=name_en,
                    joint_type=joint_type,
                    rigidbody1_index=rigid_body_a_index,
                    rigidbody2_index=rigid_body_b_index,
                    position=list(
                        cursor.unpack_field(f"{prefix}.position", "<3f", "float_vector")
                    ),
                    rotation=list(
                        cursor.unpack_field(f"{prefix}.rotation", "<3f", "float_vector")
                    ),
                    position_min=list(
                        cursor.unpack_field(
                            f"{prefix}.position_min", "<3f", "float_vector"
                        )
                    ),
                    position_max=list(
                        cursor.unpack_field(
                            f"{prefix}.position_max", "<3f", "float_vector"
                        )
                    ),
                    rotation_min=list(
                        cursor.unpack_field(
                            f"{prefix}.rotation_min", "<3f", "float_vector"
                        )
                    ),
                    rotation_max=list(
                        cursor.unpack_field(
                            f"{prefix}.rotation_max", "<3f", "float_vector"
                        )
                    ),
                    position_spring=list(
                        cursor.unpack_field(
                            f"{prefix}.position_spring", "<3f", "float_vector"
                        )
                    ),
                    rotation_spring=list(
                        cursor.unpack_field(
                            f"{prefix}.rotation_spring", "<3f", "float_vector"
                        )
                    ),
                )
            )
            cursor.mark_record(prefix, record_start)

        self._report_progress(joint_count, joint_count)
        return joints

    def _parse_soft_bodies_fast(self, more_info: bool) -> List[PmxSoftBody]:
        """Parse complete PMX 2.1 Soft Body records."""
        cursor = self._require_cursor()
        encoding = "utf-8" if self._use_utf8 else "utf-16le"
        soft_body_count = cursor.read_count("soft-body count")
        soft_bodies: List[PmxSoftBody] = []

        if more_info:
            print(f"解析 {soft_body_count} 个Soft Body...")

        config_fields = PmxSoftBodyConfig.field_names()
        cluster_fields = PmxSoftBodyCluster.field_names()
        iteration_fields = PmxSoftBodyIteration.field_names()
        material_fields = PmxSoftBodyMaterial.field_names()

        for index in range(soft_body_count):
            self._report_progress(index, soft_body_count)
            prefix = f"softbodies[{index}]"
            record_start = cursor.position
            name_jp = cursor.read_string(encoding)
            name_en = cursor.read_string(encoding)

            shape_offset = cursor.position
            shape_value = int(cursor.unpack_field(f"{prefix}.shape", "<B", "enum")[0])
            try:
                shape = SoftBodyShape(shape_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX soft-body shape {shape_value}",
                    section=cursor.section,
                    offset=shape_offset,
                ) from exc

            material_index = cursor.read_index_field(
                f"{prefix}.material_index", self._material_index_size
            )
            group_offset = cursor.position
            collision_group = int(
                cursor.unpack_field(f"{prefix}.collision_group", "<B", "int")[0]
            )
            if collision_group > 15:
                raise PmxFormatError(
                    f"Invalid PMX soft-body collision group {collision_group}",
                    section=cursor.section,
                    offset=group_offset,
                )
            collision_mask = int(
                cursor.unpack_field(f"{prefix}.collision_mask", "<H", "int")[0]
            )

            flags_offset = cursor.position
            flags_value = int(cursor.unpack_field(f"{prefix}.flags", "<B", "flags")[0])
            if flags_value & ~0x07:
                raise PmxFormatError(
                    f"Invalid PMX soft-body flags 0x{flags_value:02x}",
                    section=cursor.section,
                    offset=flags_offset,
                )

            b_link_distance = cursor.read_count_field(
                f"{prefix}.b_link_distance", "soft-body B-link distance"
            )
            cluster_count = cursor.read_count_field(
                f"{prefix}.cluster_count", "soft-body cluster count"
            )
            total_mass = float(
                cursor.unpack_field(f"{prefix}.total_mass", "<f", "float")[0]
            )
            collision_margin = float(
                cursor.unpack_field(f"{prefix}.collision_margin", "<f", "float")[0]
            )

            aero_offset = cursor.position
            aero_value = int(
                cursor.unpack_field(f"{prefix}.aero_model", "<i", "enum")[0]
            )
            try:
                aero_model = SoftBodyAeroModel(aero_value)
            except ValueError as exc:
                raise PmxFormatError(
                    f"Invalid PMX soft-body aerodynamics model {aero_value}",
                    section=cursor.section,
                    offset=aero_offset,
                ) from exc

            config_values = [
                float(cursor.unpack_field(f"{prefix}.config.{name}", "<f", "float")[0])
                for name in config_fields
            ]
            cluster_values = [
                float(cursor.unpack_field(f"{prefix}.cluster.{name}", "<f", "float")[0])
                for name in cluster_fields
            ]
            iteration_values = [
                cursor.read_count_field(
                    f"{prefix}.iteration.{name}",
                    f"soft-body {name} iteration count",
                )
                for name in iteration_fields
            ]
            material_values = [
                float(
                    cursor.unpack_field(f"{prefix}.material.{name}", "<f", "float")[0]
                )
                for name in material_fields
            ]

            anchor_count = cursor.read_count_field(
                f"{prefix}.anchor_count", "soft-body anchor count"
            )
            anchors: List[PmxSoftBodyAnchor] = []
            for anchor_index in range(anchor_count):
                anchor_prefix = f"{prefix}.anchors[{anchor_index}]"
                rigidbody_index = cursor.read_index_field(
                    f"{anchor_prefix}.rigidbody_index",
                    self._rigidbody_index_size,
                )
                vertex_index = cursor.read_index_field(
                    f"{anchor_prefix}.vertex_index",
                    self._vertex_index_size,
                    signed=False,
                )
                near_offset = cursor.position
                near_value = int(
                    cursor.unpack_field(f"{anchor_prefix}.near_mode", "<B", "bool")[0]
                )
                if near_value not in (0, 1):
                    raise PmxFormatError(
                        f"Invalid PMX soft-body anchor near mode {near_value}",
                        section=cursor.section,
                        offset=near_offset,
                    )
                anchors.append(
                    PmxSoftBodyAnchor(
                        rigidbody_index=rigidbody_index,
                        vertex_index=vertex_index,
                        near_mode=bool(near_value),
                    )
                )

            pin_count = cursor.read_count_field(
                f"{prefix}.pin_count", "soft-body pin count"
            )
            pin_vertex_indices = [
                cursor.read_index_field(
                    f"{prefix}.pin_vertex_indices[{pin_index}]",
                    self._vertex_index_size,
                    signed=False,
                )
                for pin_index in range(pin_count)
            ]

            soft_bodies.append(
                PmxSoftBody(
                    name_jp=name_jp,
                    name_en=name_en,
                    shape=shape,
                    material_index=material_index,
                    collision_group=collision_group,
                    collision_mask=collision_mask,
                    flags=SoftBodyFlags(flags_value),
                    b_link_distance=b_link_distance,
                    cluster_count=cluster_count,
                    total_mass=total_mass,
                    collision_margin=collision_margin,
                    aero_model=aero_model,
                    config=PmxSoftBodyConfig(*config_values),
                    cluster=PmxSoftBodyCluster(*cluster_values),
                    iteration=PmxSoftBodyIteration(*iteration_values),
                    material=PmxSoftBodyMaterial(*material_values),
                    anchors=anchors,
                    pin_vertex_indices=pin_vertex_indices,
                )
            )
            cursor.mark_record(prefix, record_start)

        self._report_progress(soft_body_count, soft_body_count)
        return soft_bodies

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
                bone_idx = self._io_handler.unpack_data(self._bone_index_format, data)[
                    0
                ]
                weight_data = [[bone_idx, 1.0]]
            elif weight_mode == WeightMode.BDEF2:
                bone1_idx = self._io_handler.unpack_data(self._bone_index_format, data)[
                    0
                ]
                bone2_idx = self._io_handler.unpack_data(self._bone_index_format, data)[
                    0
                ]
                bone1_weight = self._io_handler.unpack_data("f", data)[0]
                weight_data = [
                    [bone1_idx, bone1_weight],
                    [bone2_idx, 1.0 - bone1_weight],
                ]
            elif weight_mode == WeightMode.BDEF4:
                bone_indices = self._io_handler.unpack_data(
                    f"4{self._bone_index_format}", data
                )
                bone_weights = self._io_handler.unpack_data("4f", data)
                weight_data = list(zip(bone_indices, bone_weights))
            elif weight_mode == WeightMode.SDEF:
                # SDEF需要额外的C、R0、R1向量
                bone1_idx = self._io_handler.unpack_data(self._bone_index_format, data)[
                    0
                ]
                bone2_idx = self._io_handler.unpack_data(self._bone_index_format, data)[
                    0
                ]
                bone1_weight = self._io_handler.unpack_data("f", data)[0]
                # 跳过SDEF参数
                self._io_handler.unpack_data("9f", data)  # C, R0, R1向量
                weight_data = [
                    [bone1_idx, bone1_weight],
                    [bone2_idx, 1.0 - bone1_weight],
                ]

            # 边缘倍率
            edge_scale = self._io_handler.unpack_data("f", data)[0]

            # 创建顶点对象
            vertex = PmxVertex(
                position=[pos_x, pos_y, pos_z],
                normal=[norm_x, norm_y, norm_z],
                uv=[uv_u, uv_v],
                weight_mode=weight_mode,
                weight=weight_data,
                edge_scale=edge_scale,
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

    def _parse_materials(
        self, data: bytearray, textures: List[str]
    ) -> List[PmxMaterial]:
        """解析材质数据

        Args:
            data: 文件数据

        Returns:
            材质对象列表
        """
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
            tex_index = self._io_handler.unpack_data(self._texture_index_format, data)[
                0
            ]
            texture_path = textures[tex_index] if 0 <= tex_index < len(textures) else ""

            # 球面纹理索引
            sphere_index = self._io_handler.unpack_data(
                self._texture_index_format, data
            )[0]
            sphere_path = (
                textures[sphere_index] if 0 <= sphere_index < len(textures) else ""
            )
            sphere_mode = SphMode(self._io_handler.unpack_data("B", data)[0])

            # 卡通渲染
            toon_flag = self._io_handler.unpack_data("B", data)[0]
            if toon_flag == 0:
                # 使用内置卡通纹理
                toon_index = self._io_handler.unpack_data("B", data)[0]
                toon_path = f"toon{toon_index:02d}.bmp"
            else:
                # 使用自定义卡通纹理
                toon_index = self._io_handler.unpack_data(
                    self._texture_index_format, data
                )[0]
                toon_path = (
                    textures[toon_index] if 0 <= toon_index < len(textures) else ""
                )

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
                face_count=face_count,
            )

            materials.append(material)

        self._report_progress(material_count, material_count)
        return materials

    def write_file(
        self,
        pmx_model: Union[PmxModel, PmxDocument],
        file_path: Union[str, Path],
        *,
        mode: str = "canonical",
    ) -> None:
        """Write a PMX model using an explicit, fail-closed output mode."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        if not isinstance(mode, str):
            raise ValueError("PMX write mode must be a string")
        selected = mode.lower()
        if selected == "canonical":
            if not isinstance(pmx_model, PmxModel):
                raise UnsupportedPmxFeatureError(
                    "canonical write of PmxDocument",
                    available="pass document.model, or use mode='lossless_patch'",
                )
            PmxWriter(limits=self._limits).write_file(pmx_model, file_path)
            return
        if selected == "lossless_patch":
            if not isinstance(pmx_model, PmxDocument):
                raise UnsupportedPmxFeatureError(
                    "lossless_patch without PmxDocument",
                    available="load_pmx_document() followed by lossless_patch",
                )
            pmx_model.write_file(file_path)
            return
        if selected == "preserve_layout":
            raise UnsupportedPmxFeatureError(
                f"write mode {selected}",
                available="canonical PMX 2.0/2.1 or fixed-field lossless_patch",
            )
        raise ValueError(
            f"Unknown PMX write mode: {mode!r}; expected canonical, "
            "preserve_layout, or lossless_patch"
        )

    def write_file_partial(
        self, pmx_model: PmxModel, file_path: Union[str, Path]
    ) -> None:
        """Write a restricted geometry/material PMX 2.0 fixture explicitly.

        The method appends empty Bone, Morph, Display Frame, Rigid Body and
        Joint counts, so the fixture is structurally parseable to EOF.  The
        early serializer is still lossy and refuses every non-empty later
        section.  Never use it for user assets or as a successful save
        operation.

        Args:
            pmx_model: PMX模型对象
            file_path: 输出文件路径
        """
        file_path = Path(file_path)
        unsupported_sections = (
            pmx_model.bones,
            pmx_model.morphs,
            pmx_model.frames,
            pmx_model.rigidbodies,
            pmx_model.joints,
            pmx_model.softbodies,
        )
        if pmx_model.header.version >= 2.1 or any(unsupported_sections):
            raise IncompletePmxWriterError()
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
            self._vertex_index_size = lookahead_data["vertex_index_size"]
            self._material_index_size = lookahead_data["material_index_size"]

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
            binary_data.extend(
                self._encode_materials(pmx_model.materials, texture_list)
            )

            # Produce a structurally complete PMX 2.0 fixture while refusing
            # all non-empty sections that this legacy serializer cannot encode.
            # Bone, Morph, Display Frame, Rigid Body and Joint counts.
            binary_data.extend(self._io_handler.pack_data("<5i", 0, 0, 0, 0, 0))

            # 写入文件
            self._io_handler.write_file(file_path, bytes(binary_data))

            print(f"PMX文件写入完成，总大小: {len(binary_data)}字节")

        except Exception as e:
            raise ValueError(f"PMX文件写入失败: {e}") from e

    def _setup_encoding_parameters(self, pmx_model: PmxModel) -> None:
        """设置编码参数"""
        # 根据模型头部设置编码格式
        if (
            hasattr(pmx_model.header, "text_encoding")
            and pmx_model.header.text_encoding == 0
        ):
            self._use_utf8 = False
            self._io_handler.set_encoding("utf-16le")
        else:
            self._use_utf8 = True
            self._io_handler.set_encoding("utf-8")

    def _analyze_model_data(self, pmx_model: PmxModel) -> dict:
        """分析模型数据以确定最优索引大小"""
        return {
            "vertex_count": len(pmx_model.vertices),
            "material_count": len(pmx_model.materials),
            "vertex_index_size": self._determine_index_size(len(pmx_model.vertices)),
            "material_index_size": self._determine_index_size(len(pmx_model.materials)),
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
            if (
                hasattr(material, "texture_path")
                and material.texture_path
                and material.texture_path not in texture_set
            ):
                texture_set.add(material.texture_path)
                texture_list.append(material.texture_path)

            # 添加球面纹理
            if (
                hasattr(material, "sphere_path")
                and material.sphere_path
                and material.sphere_path not in texture_set
            ):
                texture_set.add(material.sphere_path)
                texture_list.append(material.sphere_path)

            # 添加toon纹理
            if (
                hasattr(material, "toon_path")
                and material.toon_path
                and material.toon_path not in texture_set
            ):
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
        global_flags = bytearray(
            [
                1 if self._use_utf8 else 0,  # 文本编码
                0,  # 附加UV数量（设为0，不写入附加UV）
                lookahead_data["vertex_index_size"],  # 顶点索引大小
                1,  # 纹理索引大小（固定为1字节）
                lookahead_data["material_index_size"],  # 材质索引大小
                2,  # 骨骼索引大小（2字节有符号short）
                1,  # 变形索引大小（固定为1字节）
                1,  # 刚体索引大小（固定为1字节）
            ]
        )

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

            # 不写入附加UV（已在header中设为0）

            # 权重类型（简化处理，使用BDEF1）
            data.extend(self._io_handler.pack_data("<B", 0))  # BDEF1
            data.extend(self._io_handler.pack_data("<h", 0))  # 骨骼索引0（2字节有符号）

            # 边缘倍率
            data.extend(
                self._io_handler.pack_data("<f", getattr(vertex, "edge_scale", 1.0))
            )

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

    def _encode_materials(
        self, materials: List[PmxMaterial], texture_list: List[str]
    ) -> bytes:
        """编码材质数据"""
        data = bytearray()

        # 材质数量
        data.extend(self._io_handler.pack_data("<I", len(materials)))

        for material in materials:
            # 材质名称
            data.extend(
                self._io_handler.write_variable_string(getattr(material, "name_jp", ""))
            )
            data.extend(
                self._io_handler.write_variable_string(getattr(material, "name_en", ""))
            )

            # 漫反射颜色
            diffuse = getattr(material, "diffuse_color", [1.0, 1.0, 1.0, 1.0])
            if len(diffuse) == 3:
                diffuse = [diffuse[0], diffuse[1], diffuse[2], 1.0]
            data.extend(
                self._io_handler.pack_data(
                    "<4f", diffuse[0], diffuse[1], diffuse[2], diffuse[3]
                )
            )

            # 镜面反射颜色和强度（分开写入：3f + f）
            specular = getattr(material, "specular_color", [1.0, 1.0, 1.0])
            specular_strength = getattr(material, "specular_strength", 0.0)
            data.extend(
                self._io_handler.pack_data("<3f", specular[0], specular[1], specular[2])
            )
            data.extend(self._io_handler.pack_data("<f", specular_strength))

            # 环境光颜色
            ambient = getattr(material, "ambient_color", [1.0, 1.0, 1.0])
            data.extend(self._io_handler.pack_data("<3f", *ambient))

            # 材质标志（简化处理）
            flags = 0x01  # 默认启用双面渲染
            data.extend(self._io_handler.pack_data("<B", flags))

            # 边缘颜色和大小
            edge_color = getattr(material, "edge_color", [0.0, 0.0, 0.0, 1.0])
            edge_size = getattr(material, "edge_size", 1.0)
            data.extend(self._io_handler.pack_data("<4f", *edge_color))
            data.extend(self._io_handler.pack_data("<f", edge_size))

            # 纹理索引（简化处理）
            tex_diffuse_idx = -1
            if hasattr(material, "texture_path") and material.texture_path:
                try:
                    tex_diffuse_idx = texture_list.index(material.texture_path)
                except ValueError:
                    tex_diffuse_idx = -1

            data.extend(self._io_handler.pack_data("<b", tex_diffuse_idx))

            # 球面纹理索引和模式
            data.extend(self._io_handler.pack_data("<b", -1))  # 无球面纹理
            data.extend(self._io_handler.pack_data("<B", 0))  # 球面模式：禁用

            # Toon模式和纹理
            data.extend(self._io_handler.pack_data("<B", 0))  # Toon模式：共享
            data.extend(self._io_handler.pack_data("<B", 0))  # Toon纹理索引

            # 备注
            data.extend(self._io_handler.write_variable_string(""))

            # 面数量
            face_count = getattr(material, "face_count", 0)
            data.extend(self._io_handler.pack_data("<I", face_count))

        return bytes(data)

    # ===== 文本解析和导出功能 =====

    def parse_text_file(
        self, file_path: Union[str, Path], more_info: bool = False
    ) -> PmxModel:
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

        with open(file_path, "r", encoding="utf-8") as f:
            lines = [
                line.strip().split("\t") if "\t" in line else [line.strip()]
                for line in f.readlines()
                if line.strip()
            ]

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
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"PMX文本文件写入完成，总行数: {len(lines)}")

    def _parse_text_header(self, lines: List[List[str]], start_idx: int) -> tuple:
        """解析PMX文本头部"""
        if (
            start_idx >= len(lines)
            or len(lines[start_idx]) != 2
            or lines[start_idx][0] != "version:"
        ):
            raise ValueError("缺少版本信息")
        version = float(lines[start_idx][1])

        if (
            start_idx + 1 >= len(lines)
            or len(lines[start_idx + 1]) != 2
            or lines[start_idx + 1][0] != "name_jp:"
        ):
            raise ValueError("缺少日语名称")
        name_jp = lines[start_idx + 1][1]

        if (
            start_idx + 2 >= len(lines)
            or len(lines[start_idx + 2]) != 2
            or lines[start_idx + 2][0] != "name_en:"
        ):
            raise ValueError("缺少英语名称")
        name_en = lines[start_idx + 2][1]

        if (
            start_idx + 3 >= len(lines)
            or len(lines[start_idx + 3]) != 2
            or lines[start_idx + 3][0] != "comment_jp:"
        ):
            raise ValueError("缺少日语备注")
        comment_jp = lines[start_idx + 3][1]

        if (
            start_idx + 4 >= len(lines)
            or len(lines[start_idx + 4]) != 2
            or lines[start_idx + 4][0] != "comment_en:"
        ):
            raise ValueError("缺少英语备注")
        comment_en = lines[start_idx + 4][1]

        header = PmxHeader(
            version=version,
            name_jp=name_jp,
            name_en=name_en,
            comment_jp=comment_jp,
            comment_en=comment_en,
        )

        return header, start_idx + 5

    def _parse_text_vertices(
        self, lines: List[List[str]], start_idx: int, more_info: bool
    ) -> tuple:
        """解析顶点数据"""
        if (
            start_idx >= len(lines)
            or len(lines[start_idx]) != 2
            or lines[start_idx][0] != "vertex_count:"
        ):
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
                    raise ValueError(
                        f"顶点数据不完整，期望{vertex_count}个顶点，只找到{i}个"
                    )

                row = lines[line_idx]
                if len(row) < 8:  # 至少需要位置、法线和UV数据
                    raise ValueError(f"顶点格式错误，期望至少8个字段，得到{len(row)}个")

                vertex = PmxVertex(
                    position=[float(row[0]), float(row[1]), float(row[2])],
                    normal=[float(row[3]), float(row[4]), float(row[5])],
                    uv=[float(row[6]), float(row[7])],
                )
                vertices.append(vertex)
                line_idx += 1

        return vertices, line_idx

    def _parse_text_faces(
        self, lines: List[List[str]], start_idx: int, more_info: bool
    ) -> tuple:
        """解析面数据"""
        if (
            start_idx >= len(lines)
            or len(lines[start_idx]) != 2
            or lines[start_idx][0] != "face_count:"
        ):
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

    def _parse_text_materials(
        self, lines: List[List[str]], start_idx: int, more_info: bool
    ) -> tuple:
        """解析材质数据"""
        if (
            start_idx >= len(lines)
            or len(lines[start_idx]) != 2
            or lines[start_idx][0] != "material_count:"
        ):
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
                    raise ValueError(
                        f"材质数据不完整，期望{material_count}个材质，只找到{i}个"
                    )

                row = lines[line_idx]
                if len(row) < 15:  # 基本材质信息
                    raise ValueError(
                        f"材质格式错误，期望至少15个字段，得到{len(row)}个"
                    )

                material = PmxMaterial(
                    name_jp=row[0],
                    name_en=row[1],
                    diffuse_color=[
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                        float(row[5]),
                    ],
                    specular_color=[float(row[6]), float(row[7]), float(row[8])],
                    specular_strength=float(row[9]),
                    ambient_color=[float(row[10]), float(row[11]), float(row[12])],
                    texture_path=row[13] if row[13] != "null" else "",
                    face_count=int(row[14]),
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
            f"comment_en:\t{header.comment_en}",
        ]

    def _format_text_vertices(self, vertices: List[PmxVertex]) -> List[str]:
        """格式化顶点为文本"""
        lines = [f"vertex_count:\t{len(vertices)}"]

        if vertices:
            # 键名行
            keys = [
                "pos_x",
                "pos_y",
                "pos_z",
                "norm_x",
                "norm_y",
                "norm_z",
                "uv_u",
                "uv_v",
            ]
            lines.append("\t".join(keys))

            for vertex in vertices:
                row = [
                    f"{vertex.position[0]:.6f}",
                    f"{vertex.position[1]:.6f}",
                    f"{vertex.position[2]:.6f}",
                    f"{vertex.normal[0]:.6f}",
                    f"{vertex.normal[1]:.6f}",
                    f"{vertex.normal[2]:.6f}",
                    f"{vertex.uv[0]:.6f}",
                    f"{vertex.uv[1]:.6f}",
                ]
                lines.append("\t".join(row))

        return lines

    def _format_text_faces(self, faces: List[List[int]]) -> List[str]:
        """格式化面为文本"""
        lines = [f"face_count:\t{len(faces)}"]

        if faces:
            lines.append("\t".join(["vertex_0", "vertex_1", "vertex_2"]))

            for face in faces:
                row = [str(face[0]), str(face[1]), str(face[2])]
                lines.append("\t".join(row))

        return lines

    def _format_text_materials(self, materials: List[PmxMaterial]) -> List[str]:
        """格式化材质为文本"""
        lines = [f"material_count:\t{len(materials)}"]

        if materials:
            keys = [
                "name_jp",
                "name_en",
                "diff_r",
                "diff_g",
                "diff_b",
                "diff_a",
                "spec_r",
                "spec_g",
                "spec_b",
                "spec_strength",
                "amb_r",
                "amb_g",
                "amb_b",
                "texture",
                "face_count",
            ]
            lines.append("\t".join(keys))

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
                    str(material.face_count),
                ]
                lines.append("\t".join(row))

        return lines

# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: nonecheck=False
"""
PyPMXVMD VMD快速解析模块 (Cython优化)

提供高性能的VMD文件解析功能。
返回与原有API兼容的VmdBoneFrame, VmdMorphFrame等对象。

优化策略:
- 使用 cdef inline 和 nogil 减少开销
- 预分配列表和数组
- 批量内存复制
- 减少中间 Python 对象创建
"""

from libc.string cimport memcpy, memchr
from libc.math cimport atan2, asin
from cpython.bytes cimport PyBytes_AS_STRING
from cpython.unicode cimport PyUnicode_Decode

# 导入原有数据模型
from pypmxvmd.common.models.vmd import (
    VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame, VmdCameraFrame,
    VmdLightFrame, VmdShadowFrame, VmdIkFrame, VmdIkBone
)

# 预计算常量
cdef double RAD_TO_DEG = 57.29577951308232  # 180.0 / PI
cdef double DEG_TO_RAD = 0.017453292519943295  # PI / 180.0
cdef double HALF_PI_DEG = 90.0


cdef class FastVmdReader:
    """VMD快速读取器

    优化点:
    - 所有方法使用 cdef inline
    - 直接指针访问
    - 批量读取
    """
    cdef bytes _data
    cdef const unsigned char* _ptr
    cdef int _pos
    cdef int _size

    def __init__(self, bytes data):
        self._data = data
        self._ptr = <const unsigned char*>PyBytes_AS_STRING(data)
        self._pos = 0
        self._size = len(data)

    cdef inline unsigned int read_uint(self):
        """读取无符号整数"""
        cdef unsigned int value
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

    cdef str read_string_fixed(self, int length):
        """读取固定长度Shift-JIS字符串（零拷贝优化）"""
        cdef const unsigned char* start = self._ptr + self._pos
        cdef const unsigned char* end_ptr
        cdef int actual_len

        # 立即推进位置指针
        self._pos += length

        # 在 [start, start + length) 范围内查找 null 终止符
        end_ptr = <const unsigned char*>memchr(start, 0, length)

        if end_ptr != NULL:
            actual_len = end_ptr - start
        else:
            actual_len = length

        # 使用 C-API 直接从指针解码，避免创建临时 bytes 对象
        return PyUnicode_Decode(<const char*>start, actual_len, "shift_jis", "ignore")


cdef inline void quaternion_to_euler_ptr(
    double qx, double qy, double qz, double qw,
    double* out_r, double* out_p, double* out_y
) noexcept nogil:
    """四元数转欧拉角 (指针返回，nogil，避免元组开销)"""
    cdef double sinr_cosp, cosr_cosp, sinp, siny_cosp, cosy_cosp

    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    out_r[0] = atan2(sinr_cosp, cosr_cosp) * RAD_TO_DEG

    sinp = 2.0 * (qw * qy - qz * qx)
    if sinp >= 1.0:
        out_p[0] = HALF_PI_DEG
    elif sinp <= -1.0:
        out_p[0] = -HALF_PI_DEG
    else:
        out_p[0] = asin(sinp) * RAD_TO_DEG

    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    out_y[0] = atan2(siny_cosp, cosy_cosp) * RAD_TO_DEG


cpdef parse_vmd_cython(bytes data, bint more_info=False):
    """使用Cython解析VMD文件数据

    Args:
        data: VMD文件的二进制数据
        more_info: 是否显示详细信息

    Returns:
        VmdMotion对象 (与原有API完全兼容)
    """
    cdef FastVmdReader reader = FastVmdReader(data)

    # 解析头部
    cdef str magic = reader.read_string_fixed(21)
    if 'Vocaloid Motion Data' not in magic:
        raise ValueError(f"无效的VMD魔术字符串: '{magic}'")

    cdef str version_str = reader.read_string_fixed(4)
    cdef int version
    cdef int name_length

    if version_str == '0002':
        version = 2
        name_length = 20
    else:
        version = 1
        name_length = 10

    reader.skip(5)  # padding
    cdef str model_name = reader.read_string_fixed(name_length)

    # 创建VMD对象
    cdef object vmd = VmdMotion()
    vmd.header = VmdHeader(version=version, model_name=model_name)

    # 解析各个部分
    vmd.bone_frames = _parse_bone_frames_cython(reader, more_info)
    vmd.morph_frames = _parse_morph_frames_cython(reader, more_info)
    vmd.camera_frames = _parse_camera_frames_cython(reader, more_info)
    vmd.light_frames = _parse_light_frames_cython(reader, more_info)
    vmd.shadow_frames = _parse_shadow_frames_cython(reader, more_info)
    vmd.ik_frames = _parse_ik_frames_cython(reader, more_info)

    if more_info:
        print(f"VMD Cython解析完成: {len(vmd.bone_frames)}个骨骼帧, "
              f"{len(vmd.morph_frames)}个变形帧")

    return vmd


cdef list _parse_bone_frames_cython(FastVmdReader reader, bint more_info):
    """解析骨骼帧 (Cython优化)

    优化点:
    - 批量读取位置和旋转数据
    - 预计算插值数组
    - 优化物理开关检测逻辑
    """
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    # 预分配列表
    cdef list bone_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个骨骼帧...")

    cdef unsigned int i
    cdef str bone_name
    cdef unsigned int frame_num
    cdef float px, py, pz, qx, qy, qz, qw
    cdef double r_val, p_val, y_val
    cdef bint physics_disabled

    # 插值数据变量 - 使用数组优化
    cdef signed char interp[16]
    cdef signed char phys1, phys2, z_ax, r_ax
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        # 骨骼名称 (15字节)
        bone_name = reader.read_string_fixed(15)

        # 帧号 - 直接从指针读取
        memcpy(&frame_num, ptr + reader._pos, 4)
        reader._pos += 4

        # 位置 - 批量读取12字节
        memcpy(&px, ptr + reader._pos, 4)
        memcpy(&py, ptr + reader._pos + 4, 4)
        memcpy(&pz, ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 旋转四元数 - 批量读取16字节
        memcpy(&qx, ptr + reader._pos, 4)
        memcpy(&qy, ptr + reader._pos + 4, 4)
        memcpy(&qz, ptr + reader._pos + 8, 4)
        memcpy(&qw, ptr + reader._pos + 12, 4)
        reader._pos += 16

        # 四元数转欧拉角 (直接写入变量，避免元组解包)
        quaternion_to_euler_ptr(qx, qy, qz, qw, &r_val, &p_val, &y_val)

        # 读取插值数据 (64字节) - 优化: 只读取需要的字节
        # 布局: [x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay,
        #        x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by, ?, z_ax, r_ax, ...]
        interp[0] = <signed char>ptr[reader._pos]      # x_ax
        interp[1] = <signed char>ptr[reader._pos + 4]  # x_ay
        interp[2] = <signed char>ptr[reader._pos + 8]  # x_bx
        interp[3] = <signed char>ptr[reader._pos + 12] # x_by
        interp[4] = <signed char>ptr[reader._pos + 1]  # y_ax
        interp[5] = <signed char>ptr[reader._pos + 5]  # y_ay
        interp[6] = <signed char>ptr[reader._pos + 9]  # y_bx
        interp[7] = <signed char>ptr[reader._pos + 13] # y_by
        interp[8] = <signed char>ptr[reader._pos + 17] # z_ax
        interp[9] = <signed char>ptr[reader._pos + 6]  # z_ay
        interp[10] = <signed char>ptr[reader._pos + 10] # z_bx
        interp[11] = <signed char>ptr[reader._pos + 14] # z_by
        interp[12] = <signed char>ptr[reader._pos + 18] # r_ax
        interp[13] = <signed char>ptr[reader._pos + 7]  # r_ay
        interp[14] = <signed char>ptr[reader._pos + 11] # r_bx
        interp[15] = <signed char>ptr[reader._pos + 15] # r_by

        # 物理开关检测
        phys1 = <signed char>ptr[reader._pos + 2]
        phys2 = <signed char>ptr[reader._pos + 3]
        z_ax = interp[8]
        r_ax = interp[12]

        reader._pos += 64

        # 优化的物理开关判断
        if phys1 == z_ax and phys2 == r_ax:
            physics_disabled = False
        elif phys1 == 0 and phys2 == 0:
            physics_disabled = False
        elif phys1 == 99 and phys2 == 15:
            physics_disabled = True
        else:
            physics_disabled = True

        # 创建骨骼帧对象 - 使用预构建的列表
        bone_frames[i] = VmdBoneFrame(
            bone_name=bone_name,
            frame_number=frame_num,
            position=[px, py, pz],
            rotation=[r_val, p_val, y_val],
            interpolation=[
                interp[0], interp[1], interp[2], interp[3],   # X轴
                interp[4], interp[5], interp[6], interp[7],   # Y轴
                interp[8], interp[9], interp[10], interp[11], # Z轴
                interp[12], interp[13], interp[14], interp[15] # 旋转
            ],
            physics_disabled=physics_disabled
        )

    return bone_frames


cdef list _parse_morph_frames_cython(FastVmdReader reader, bint more_info):
    """解析变形帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list morph_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个变形帧...")

    cdef unsigned int i
    cdef str morph_name
    cdef unsigned int frame_num
    cdef float weight
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        # 变形名称 (15字节)
        morph_name = reader.read_string_fixed(15)

        # 帧号和权重 - 批量读取
        memcpy(&frame_num, ptr + reader._pos, 4)
        memcpy(&weight, ptr + reader._pos + 4, 4)
        reader._pos += 8

        morph_frames[i] = VmdMorphFrame(
            morph_name=morph_name,
            frame_number=frame_num,
            weight=weight
        )

    return morph_frames


cdef list _parse_camera_frames_cython(FastVmdReader reader, bint more_info):
    """解析相机帧 (Cython优化)

    优化点:
    - 使用固定大小数组读取插值数据
    - 批量内存复制
    """
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list camera_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个相机帧...")

    cdef unsigned int i, j
    cdef unsigned int frame_num
    cdef float distance, px, py, pz, rx, ry, rz
    cdef unsigned int fov
    cdef unsigned char perspective
    cdef signed char interp_arr[24]
    cdef list interpolation
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        # 帧号
        memcpy(&frame_num, ptr + reader._pos, 4)
        reader._pos += 4

        # 距离
        memcpy(&distance, ptr + reader._pos, 4)
        reader._pos += 4

        # 位置 - 批量读取
        memcpy(&px, ptr + reader._pos, 4)
        memcpy(&py, ptr + reader._pos + 4, 4)
        memcpy(&pz, ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 旋转 (弧度) - 批量读取
        memcpy(&rx, ptr + reader._pos, 4)
        memcpy(&ry, ptr + reader._pos + 4, 4)
        memcpy(&rz, ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 插值数据 (24字节) - 批量复制到数组
        memcpy(interp_arr, ptr + reader._pos, 24)
        reader._pos += 24

        # 转换为Python列表
        interpolation = [
            interp_arr[0], interp_arr[1], interp_arr[2], interp_arr[3],
            interp_arr[4], interp_arr[5], interp_arr[6], interp_arr[7],
            interp_arr[8], interp_arr[9], interp_arr[10], interp_arr[11],
            interp_arr[12], interp_arr[13], interp_arr[14], interp_arr[15],
            interp_arr[16], interp_arr[17], interp_arr[18], interp_arr[19],
            interp_arr[20], interp_arr[21], interp_arr[22], interp_arr[23]
        ]

        # FOV和透视
        memcpy(&fov, ptr + reader._pos, 4)
        perspective = ptr[reader._pos + 4]
        reader._pos += 5

        camera_frames[i] = VmdCameraFrame(
            frame_number=frame_num,
            distance=distance,
            position=[px, py, pz],
            rotation=[rx * RAD_TO_DEG, ry * RAD_TO_DEG, rz * RAD_TO_DEG],
            interpolation=interpolation,
            fov=fov,
            perspective=bool(perspective)
        )

    return camera_frames


cdef list _parse_light_frames_cython(FastVmdReader reader, bint more_info):
    """解析光源帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list light_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个光源帧...")

    cdef unsigned int i
    cdef unsigned int frame_num
    cdef float r, g, b, x, y, z
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        # 批量读取所有数据 (28字节)
        memcpy(&frame_num, ptr + reader._pos, 4)
        memcpy(&r, ptr + reader._pos + 4, 4)
        memcpy(&g, ptr + reader._pos + 8, 4)
        memcpy(&b, ptr + reader._pos + 12, 4)
        memcpy(&x, ptr + reader._pos + 16, 4)
        memcpy(&y, ptr + reader._pos + 20, 4)
        memcpy(&z, ptr + reader._pos + 24, 4)
        reader._pos += 28

        light_frames[i] = VmdLightFrame(
            frame_number=frame_num,
            color=[r, g, b],
            position=[x, y, z]
        )

    return light_frames


cdef list _parse_shadow_frames_cython(FastVmdReader reader, bint more_info):
    """解析阴影帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list shadow_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个阴影帧...")

    cdef unsigned int i
    cdef unsigned int frame_num
    cdef signed char mode
    cdef float distance
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        # 批量读取 (9字节)
        memcpy(&frame_num, ptr + reader._pos, 4)
        mode = <signed char>ptr[reader._pos + 4]
        memcpy(&distance, ptr + reader._pos + 5, 4)
        reader._pos += 9

        shadow_frames[i] = VmdShadowFrame(
            frame_number=frame_num,
            shadow_mode=mode,
            distance=distance
        )

    return shadow_frames


cdef list _parse_ik_frames_cython(FastVmdReader reader, bint more_info):
    """解析IK帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list ik_frames = [None] * frame_count

    if more_info:
        print(f"解析 {frame_count} 个IK帧...")

    cdef unsigned int i, j
    cdef unsigned int frame_num, ik_count
    cdef unsigned char display, ik_enabled
    cdef str bone_name
    cdef list ik_bones
    cdef const unsigned char* ptr = reader._ptr

    for i in range(frame_count):
        memcpy(&frame_num, ptr + reader._pos, 4)
        display = ptr[reader._pos + 4]
        memcpy(&ik_count, ptr + reader._pos + 5, 4)
        reader._pos += 9

        # IK bones - 预分配列表
        ik_bones = [None] * ik_count
        for j in range(ik_count):
            bone_name = reader.read_string_fixed(20)
            ik_enabled = ptr[reader._pos]
            reader._pos += 1

            ik_bones[j] = VmdIkBone(
                bone_name=bone_name,
                ik_enabled=bool(ik_enabled)
            )

        ik_frames[i] = VmdIkFrame(
            frame_number=frame_num,
            display=bool(display),
            ik_bones=ik_bones
        )

    return ik_frames

# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
"""
PyPMXVMD VMD快速解析模块 (Cython优化)

提供高性能的VMD文件解析功能。
返回与原有API兼容的VmdBoneFrame, VmdMorphFrame等对象。
"""

from libc.string cimport memcpy
from libc.math cimport atan2, asin, cos, sin, M_PI
from cpython.bytes cimport PyBytes_AS_STRING

# 导入原有数据模型
from pypmxvmd.common.models.vmd import (
    VmdMotion, VmdHeader, VmdBoneFrame, VmdMorphFrame, VmdCameraFrame,
    VmdLightFrame, VmdShadowFrame, VmdIkFrame, VmdIkBone
)

# 弧度转角度常量
cdef double RAD_TO_DEG = 180.0 / M_PI
cdef double DEG_TO_RAD = M_PI / 180.0


cdef class FastVmdReader:
    """VMD快速读取器"""
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
        """读取固定长度Shift-JIS字符串"""
        cdef bytes raw = self._data[self._pos:self._pos + length]
        self._pos += length

        # 查找null终止符
        cdef int null_pos = raw.find(b'\x00')
        if null_pos != -1:
            raw = raw[:null_pos]

        try:
            return raw.decode('shift_jis')
        except:
            return raw.decode('shift_jis', errors='ignore')


cdef inline tuple quaternion_to_euler(double qx, double qy, double qz, double qw):
    """四元数转欧拉角 (内联优化)"""
    cdef double sinr_cosp, cosr_cosp, sinp, siny_cosp, cosy_cosp
    cdef double roll, pitch, yaw

    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (qw * qy - qz * qx)
    if sinp >= 1.0:
        pitch = M_PI / 2.0
    elif sinp <= -1.0:
        pitch = -M_PI / 2.0
    else:
        pitch = asin(sinp)

    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = atan2(siny_cosp, cosy_cosp)

    return (roll * RAD_TO_DEG, pitch * RAD_TO_DEG, yaw * RAD_TO_DEG)


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

    # 解析骨骼帧
    vmd.bone_frames = _parse_bone_frames_cython(reader, more_info)

    # 解析变形帧
    vmd.morph_frames = _parse_morph_frames_cython(reader, more_info)

    # 解析相机帧
    vmd.camera_frames = _parse_camera_frames_cython(reader, more_info)

    # 解析光源帧
    vmd.light_frames = _parse_light_frames_cython(reader, more_info)

    # 解析阴影帧
    vmd.shadow_frames = _parse_shadow_frames_cython(reader, more_info)

    # 解析IK帧
    vmd.ik_frames = _parse_ik_frames_cython(reader, more_info)

    if more_info:
        print(f"VMD Cython解析完成: {len(vmd.bone_frames)}个骨骼帧, "
              f"{len(vmd.morph_frames)}个变形帧")

    return vmd


cdef list _parse_bone_frames_cython(FastVmdReader reader, bint more_info):
    """解析骨骼帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list bone_frames = []

    if more_info:
        print(f"解析 {frame_count} 个骨骼帧...")

    cdef unsigned int i
    cdef str bone_name
    cdef unsigned int frame_num
    cdef float px, py, pz, qx, qy, qz, qw
    cdef tuple euler
    cdef list position, rotation, interpolation
    cdef bint physics_disabled

    # 插值数据相关变量
    cdef signed char x_ax, y_ax, phys1, phys2, x_ay, y_ay, z_ay, r_ay
    cdef signed char x_bx, y_bx, z_bx, r_bx, x_by, y_by, z_by, r_by
    cdef signed char z_ax, r_ax

    for i in range(frame_count):
        # 骨骼名称 (15字节)
        bone_name = reader.read_string_fixed(15)

        # 帧号
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 位置
        memcpy(&px, reader._ptr + reader._pos, 4)
        memcpy(&py, reader._ptr + reader._pos + 4, 4)
        memcpy(&pz, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 旋转四元数
        memcpy(&qx, reader._ptr + reader._pos, 4)
        memcpy(&qy, reader._ptr + reader._pos + 4, 4)
        memcpy(&qz, reader._ptr + reader._pos + 8, 4)
        memcpy(&qw, reader._ptr + reader._pos + 12, 4)
        reader._pos += 16

        # 四元数转欧拉角
        euler = quaternion_to_euler(qx, qy, qz, qw)

        # 读取插值数据 (64字节)
        # 格式: "<bb bb 12b xbb 45x" 总共64字节
        x_ax = <signed char>reader._ptr[reader._pos]
        y_ax = <signed char>reader._ptr[reader._pos + 1]
        phys1 = <signed char>reader._ptr[reader._pos + 2]
        phys2 = <signed char>reader._ptr[reader._pos + 3]
        x_ay = <signed char>reader._ptr[reader._pos + 4]
        y_ay = <signed char>reader._ptr[reader._pos + 5]
        z_ay = <signed char>reader._ptr[reader._pos + 6]
        r_ay = <signed char>reader._ptr[reader._pos + 7]
        x_bx = <signed char>reader._ptr[reader._pos + 8]
        y_bx = <signed char>reader._ptr[reader._pos + 9]
        z_bx = <signed char>reader._ptr[reader._pos + 10]
        r_bx = <signed char>reader._ptr[reader._pos + 11]
        x_by = <signed char>reader._ptr[reader._pos + 12]
        y_by = <signed char>reader._ptr[reader._pos + 13]
        z_by = <signed char>reader._ptr[reader._pos + 14]
        r_by = <signed char>reader._ptr[reader._pos + 15]
        # 跳过1字节
        z_ax = <signed char>reader._ptr[reader._pos + 17]
        r_ax = <signed char>reader._ptr[reader._pos + 18]
        reader._pos += 64

        # 检测物理开关状态
        if (phys1, phys2) == (z_ax, r_ax):
            physics_disabled = False
        elif (phys1, phys2) == (0, 0):
            physics_disabled = False
        elif (phys1, phys2) == (99, 15):
            physics_disabled = True
        else:
            physics_disabled = True

        # 构建插值数据
        interpolation = [
            x_ax, x_ay, x_bx, x_by,  # X轴
            y_ax, y_ay, y_bx, y_by,  # Y轴
            z_ax, z_ay, z_bx, z_by,  # Z轴
            r_ax, r_ay, r_bx, r_by   # 旋转
        ]

        # 创建骨骼帧对象
        bone_frames.append(VmdBoneFrame(
            bone_name=bone_name,
            frame_number=frame_num,
            position=[px, py, pz],
            rotation=list(euler),
            interpolation=interpolation,
            physics_disabled=physics_disabled
        ))

    return bone_frames


cdef list _parse_morph_frames_cython(FastVmdReader reader, bint more_info):
    """解析变形帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list morph_frames = []

    if more_info:
        print(f"解析 {frame_count} 个变形帧...")

    cdef unsigned int i
    cdef str morph_name
    cdef unsigned int frame_num
    cdef float weight

    for i in range(frame_count):
        # 变形名称 (15字节)
        morph_name = reader.read_string_fixed(15)

        # 帧号和权重
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        memcpy(&weight, reader._ptr + reader._pos + 4, 4)
        reader._pos += 8

        morph_frames.append(VmdMorphFrame(
            morph_name=morph_name,
            frame_number=frame_num,
            weight=weight
        ))

    return morph_frames


cdef list _parse_camera_frames_cython(FastVmdReader reader, bint more_info):
    """解析相机帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list camera_frames = []

    if more_info:
        print(f"解析 {frame_count} 个相机帧...")

    cdef unsigned int i
    cdef unsigned int frame_num
    cdef float distance, px, py, pz, rx, ry, rz
    cdef unsigned int fov
    cdef unsigned char perspective
    cdef list position, rotation, interpolation

    for i in range(frame_count):
        # 帧号
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 距离
        memcpy(&distance, reader._ptr + reader._pos, 4)
        reader._pos += 4

        # 位置
        memcpy(&px, reader._ptr + reader._pos, 4)
        memcpy(&py, reader._ptr + reader._pos + 4, 4)
        memcpy(&pz, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 旋转 (弧度)
        memcpy(&rx, reader._ptr + reader._pos, 4)
        memcpy(&ry, reader._ptr + reader._pos + 4, 4)
        memcpy(&rz, reader._ptr + reader._pos + 8, 4)
        reader._pos += 12

        # 插值数据 (24字节)
        interpolation = []
        for j in range(24):
            interpolation.append(<signed char>reader._ptr[reader._pos + j])
        reader._pos += 24

        # FOV和透视
        memcpy(&fov, reader._ptr + reader._pos, 4)
        perspective = reader._ptr[reader._pos + 4]
        reader._pos += 5

        camera_frames.append(VmdCameraFrame(
            frame_number=frame_num,
            distance=distance,
            position=[px, py, pz],
            rotation=[rx * RAD_TO_DEG, ry * RAD_TO_DEG, rz * RAD_TO_DEG],
            interpolation=interpolation,
            fov=fov,
            perspective=bool(perspective)
        ))

    return camera_frames


cdef list _parse_light_frames_cython(FastVmdReader reader, bint more_info):
    """解析光源帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list light_frames = []

    if more_info:
        print(f"解析 {frame_count} 个光源帧...")

    cdef unsigned int i
    cdef unsigned int frame_num
    cdef float r, g, b, x, y, z

    for i in range(frame_count):
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        memcpy(&r, reader._ptr + reader._pos + 4, 4)
        memcpy(&g, reader._ptr + reader._pos + 8, 4)
        memcpy(&b, reader._ptr + reader._pos + 12, 4)
        memcpy(&x, reader._ptr + reader._pos + 16, 4)
        memcpy(&y, reader._ptr + reader._pos + 20, 4)
        memcpy(&z, reader._ptr + reader._pos + 24, 4)
        reader._pos += 28

        light_frames.append(VmdLightFrame(
            frame_number=frame_num,
            color=[r, g, b],
            position=[x, y, z]
        ))

    return light_frames


cdef list _parse_shadow_frames_cython(FastVmdReader reader, bint more_info):
    """解析阴影帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list shadow_frames = []

    if more_info:
        print(f"解析 {frame_count} 个阴影帧...")

    cdef unsigned int i
    cdef unsigned int frame_num
    cdef signed char mode
    cdef float distance

    for i in range(frame_count):
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        mode = <signed char>reader._ptr[reader._pos + 4]
        memcpy(&distance, reader._ptr + reader._pos + 5, 4)
        reader._pos += 9

        shadow_frames.append(VmdShadowFrame(
            frame_number=frame_num,
            shadow_mode=mode,
            distance=distance
        ))

    return shadow_frames


cdef list _parse_ik_frames_cython(FastVmdReader reader, bint more_info):
    """解析IK帧 (Cython优化)"""
    if reader._size - reader._pos < 4:
        return []

    cdef unsigned int frame_count = reader.read_uint()
    cdef list ik_frames = []

    if more_info:
        print(f"解析 {frame_count} 个IK帧...")

    cdef unsigned int i, j
    cdef unsigned int frame_num, ik_count
    cdef unsigned char display, ik_enabled
    cdef str bone_name
    cdef list ik_bones

    for i in range(frame_count):
        memcpy(&frame_num, reader._ptr + reader._pos, 4)
        display = reader._ptr[reader._pos + 4]
        memcpy(&ik_count, reader._ptr + reader._pos + 5, 4)
        reader._pos += 9

        ik_bones = []
        for j in range(ik_count):
            bone_name = reader.read_string_fixed(20)
            ik_enabled = reader._ptr[reader._pos]
            reader._pos += 1

            ik_bones.append(VmdIkBone(
                bone_name=bone_name,
                ik_enabled=bool(ik_enabled)
            ))

        ik_frames.append(VmdIkFrame(
            frame_number=frame_num,
            display=bool(display),
            ik_bones=ik_bones
        ))

    return ik_frames

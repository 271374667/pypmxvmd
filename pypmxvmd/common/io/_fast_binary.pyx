# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: nonecheck=False
"""
PyPMXVMD 快速二进制读取模块 (Cython优化)

提供高性能的二进制数据解析功能。
编译后无需额外依赖即可运行。

优化策略:
- 使用 cdef inline 减少函数调用开销
- 使用 memchr 快速查找 null 终止符
- 使用 PyUnicode_Decode 零拷贝字符串解码
- 预计算常量避免运行时计算
"""

from libc.string cimport memcpy, memchr
from libc.math cimport atan2, asin, cos, sin, sqrt
from cpython.bytes cimport PyBytes_AS_STRING
from cpython.unicode cimport PyUnicode_Decode


# 预计算常量 (避免运行时除法)
cdef double _PI = 3.14159265358979323846
cdef double RAD_TO_DEG = 57.29577951308232  # 180.0 / PI
cdef double DEG_TO_RAD = 0.017453292519943295  # PI / 180.0

# 预计算常用角度
cdef double HALF_PI_DEG = 90.0


cdef class FastBinaryReader:
    """快速二进制读取器

    使用Cython优化的二进制数据读取，避免Python层面的开销。

    优化点:
    - 所有内部方法使用 cdef inline
    - 直接指针访问，避免Python切片
    - 批量读取优化
    """
    cdef bytes _data
    cdef const unsigned char* _ptr
    cdef int _pos
    cdef int _size

    def __init__(self, bytes data):
        """初始化读取器

        Args:
            data: 二进制数据
        """
        self._data = data
        self._ptr = <const unsigned char*>PyBytes_AS_STRING(data)
        self._pos = 0
        self._size = len(data)

    # ===== 公共API方法 (cpdef) =====

    cpdef int get_position(self):
        """获取当前读取位置"""
        return self._pos

    cpdef void set_position(self, int pos):
        """设置读取位置"""
        self._pos = pos

    cpdef int get_remaining(self):
        """获取剩余字节数"""
        return self._size - self._pos

    cpdef void skip(self, int count):
        """跳过指定字节数"""
        self._pos += count

    cpdef unsigned char read_byte(self):
        """读取单字节"""
        cdef unsigned char value = self._ptr[self._pos]
        self._pos += 1
        return value

    cpdef signed char read_sbyte(self):
        """读取有符号字节"""
        cdef signed char value = <signed char>self._ptr[self._pos]
        self._pos += 1
        return value

    cpdef unsigned short read_ushort(self):
        """读取无符号短整数 (小端)"""
        cdef unsigned short value
        memcpy(&value, self._ptr + self._pos, 2)
        self._pos += 2
        return value

    cpdef short read_short(self):
        """读取有符号短整数 (小端)"""
        cdef short value
        memcpy(&value, self._ptr + self._pos, 2)
        self._pos += 2
        return value

    cpdef unsigned int read_uint(self):
        """读取无符号整数 (小端)"""
        cdef unsigned int value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cpdef int read_int(self):
        """读取有符号整数 (小端)"""
        cdef int value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cpdef float read_float(self):
        """读取单精度浮点数"""
        cdef float value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cpdef tuple read_float3(self):
        """读取3个浮点数"""
        cdef float x, y, z
        memcpy(&x, self._ptr + self._pos, 4)
        memcpy(&y, self._ptr + self._pos + 4, 4)
        memcpy(&z, self._ptr + self._pos + 8, 4)
        self._pos += 12
        return (x, y, z)

    cpdef tuple read_float4(self):
        """读取4个浮点数"""
        cdef float x, y, z, w
        memcpy(&x, self._ptr + self._pos, 4)
        memcpy(&y, self._ptr + self._pos + 4, 4)
        memcpy(&z, self._ptr + self._pos + 8, 4)
        memcpy(&w, self._ptr + self._pos + 12, 4)
        self._pos += 16
        return (x, y, z, w)

    cpdef bytes read_bytes(self, int count):
        """读取指定字节数"""
        cdef bytes result = self._data[self._pos:self._pos + count]
        self._pos += count
        return result

    cpdef str read_string_fixed(self, int length, str encoding='shift_jis'):
        """读取固定长度字符串 (零拷贝优化)

        Args:
            length: 字符串长度
            encoding: 编码格式

        Returns:
            解码后的字符串
        """
        cdef const unsigned char* start = self._ptr + self._pos
        cdef const unsigned char* end_ptr
        cdef int actual_len
        cdef bytes enc_bytes
        cdef const char* enc_c_str

        # 立即推进位置指针
        self._pos += length

        # 使用 memchr 快速查找 null 终止符
        end_ptr = <const unsigned char*>memchr(start, 0, length)

        if end_ptr != NULL:
            actual_len = end_ptr - start
        else:
            actual_len = length

        # 转换编码字符串为C字符串
        enc_bytes = encoding.encode('ascii')
        enc_c_str = <const char*>PyBytes_AS_STRING(enc_bytes)

        # 使用 C-API 直接从指针解码，避免创建临时 bytes 对象
        return PyUnicode_Decode(<const char*>start, actual_len, enc_c_str, "ignore")

    cpdef str read_string_variable(self, str encoding='utf-16le'):
        """读取变长字符串 (前4字节为长度)

        Args:
            encoding: 编码格式

        Returns:
            解码后的字符串
        """
        cdef unsigned int length
        cdef const char* start
        cdef bytes enc_bytes
        cdef const char* enc_c_str

        # 读取长度
        memcpy(&length, self._ptr + self._pos, 4)
        self._pos += 4

        if length == 0:
            return ""

        start = <const char*>(self._ptr + self._pos)
        self._pos += length

        # 转换编码字符串
        enc_bytes = encoding.encode('ascii')
        enc_c_str = <const char*>PyBytes_AS_STRING(enc_bytes)

        # 直接使用C API解码
        return PyUnicode_Decode(start, length, enc_c_str, "ignore")

    cpdef int read_index(self, int size, bint signed=True):
        """读取索引值

        Args:
            size: 索引字节数 (1, 2, 或 4)
            signed: 是否有符号

        Returns:
            索引值
        """
        cdef int value
        cdef unsigned int uvalue

        if size == 1:
            if signed:
                return <signed char>self._ptr[self._pos]
            else:
                value = self._ptr[self._pos]
            self._pos += 1
            return value
        elif size == 2:
            if signed:
                memcpy(&value, self._ptr + self._pos, 2)
                self._pos += 2
                return <short>value
            else:
                memcpy(&uvalue, self._ptr + self._pos, 2)
                self._pos += 2
                return <unsigned short>uvalue
        else:  # size == 4
            if signed:
                memcpy(&value, self._ptr + self._pos, 4)
            else:
                memcpy(&uvalue, self._ptr + self._pos, 4)
                value = uvalue
            self._pos += 4
            return value

    # ===== 内部优化方法 (cdef inline) =====

    cdef inline unsigned char _read_byte_fast(self):
        """内部快速读取单字节"""
        cdef unsigned char value = self._ptr[self._pos]
        self._pos += 1
        return value

    cdef inline unsigned int _read_uint_fast(self):
        """内部快速读取无符号整数"""
        cdef unsigned int value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cdef inline float _read_float_fast(self):
        """内部快速读取浮点数"""
        cdef float value
        memcpy(&value, self._ptr + self._pos, 4)
        self._pos += 4
        return value

    cdef inline void _read_float3_into(self, float* out):
        """内部快速读取3个浮点数到指针"""
        memcpy(out, self._ptr + self._pos, 12)
        self._pos += 12

    cdef inline void _read_float4_into(self, float* out):
        """内部快速读取4个浮点数到指针"""
        memcpy(out, self._ptr + self._pos, 16)
        self._pos += 16


# ===== 四元数/欧拉角转换函数 =====

cdef inline void _quaternion_to_euler_ptr(
    double qx, double qy, double qz, double qw,
    double* out_r, double* out_p, double* out_y
) noexcept nogil:
    """四元数转欧拉角 (内部版本，指针返回，nogil)

    使用指针避免元组创建开销，nogil 允许并行化
    """
    cdef double sinr_cosp, cosr_cosp, sinp, siny_cosp, cosy_cosp

    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    out_r[0] = atan2(sinr_cosp, cosr_cosp) * RAD_TO_DEG

    # Pitch (y-axis rotation) - 使用预计算常量
    sinp = 2.0 * (qw * qy - qz * qx)
    if sinp >= 1.0:
        out_p[0] = HALF_PI_DEG
    elif sinp <= -1.0:
        out_p[0] = -HALF_PI_DEG
    else:
        out_p[0] = asin(sinp) * RAD_TO_DEG

    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    out_y[0] = atan2(siny_cosp, cosy_cosp) * RAD_TO_DEG


cpdef tuple quaternion_to_euler_fast(double qx, double qy, double qz, double qw):
    """将四元数转换为欧拉角 (度)

    Args:
        qx, qy, qz, qw: 四元数分量

    Returns:
        (roll, pitch, yaw) 欧拉角 (度)
    """
    cdef double roll, pitch, yaw

    _quaternion_to_euler_ptr(qx, qy, qz, qw, &roll, &pitch, &yaw)

    return (roll, pitch, yaw)


cdef inline void _euler_to_quaternion_ptr(
    double roll_deg, double pitch_deg, double yaw_deg,
    double* out_w, double* out_x, double* out_y, double* out_z
) noexcept nogil:
    """欧拉角转四元数 (内部版本，指针返回，nogil)"""
    cdef double roll = roll_deg * DEG_TO_RAD
    cdef double pitch = pitch_deg * DEG_TO_RAD
    cdef double yaw = yaw_deg * DEG_TO_RAD

    cdef double cy = cos(yaw * 0.5)
    cdef double sy = sin(yaw * 0.5)
    cdef double cp = cos(pitch * 0.5)
    cdef double sp = sin(pitch * 0.5)
    cdef double cr = cos(roll * 0.5)
    cdef double sr = sin(roll * 0.5)

    out_w[0] = cr * cp * cy + sr * sp * sy
    out_x[0] = sr * cp * cy - cr * sp * sy
    out_y[0] = cr * sp * cy + sr * cp * sy
    out_z[0] = cr * cp * sy - sr * sp * cy


cpdef tuple euler_to_quaternion_fast(double roll_deg, double pitch_deg, double yaw_deg):
    """将欧拉角转换为四元数

    Args:
        roll_deg, pitch_deg, yaw_deg: 欧拉角 (度)

    Returns:
        (qw, qx, qy, qz) 四元数
    """
    cdef double w, x, y, z

    _euler_to_quaternion_ptr(roll_deg, pitch_deg, yaw_deg, &w, &x, &y, &z)

    return (w, x, y, z)

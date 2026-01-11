# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
"""
PyPMXVMD 快速二进制读取模块 (Cython优化)

提供高性能的二进制数据解析功能。
编译后无需额外依赖即可运行。
"""

from libc.string cimport memcpy
from libc.math cimport atan2, asin, cos, sin, sqrt, M_PI
from cpython.bytes cimport PyBytes_AS_STRING
from cpython cimport array
import struct


# 弧度转角度常量
cdef double RAD_TO_DEG = 180.0 / M_PI


cdef class FastBinaryReader:
    """快速二进制读取器

    使用Cython优化的二进制数据读取，避免Python层面的开销。
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
        """读取固定长度字符串

        Args:
            length: 字符串长度
            encoding: 编码格式

        Returns:
            解码后的字符串
        """
        cdef bytes raw = self._data[self._pos:self._pos + length]
        self._pos += length

        # 查找null终止符
        cdef int null_pos = raw.find(b'\x00')
        if null_pos != -1:
            raw = raw[:null_pos]

        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            return raw.decode(encoding, errors='ignore')

    cpdef str read_string_variable(self, str encoding='utf-16le'):
        """读取变长字符串 (前4字节为长度)

        Args:
            encoding: 编码格式

        Returns:
            解码后的字符串
        """
        cdef unsigned int length = self.read_uint()
        if length == 0:
            return ""

        cdef bytes raw = self._data[self._pos:self._pos + length]
        self._pos += length

        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            return raw.decode(encoding, errors='ignore')

    cpdef int read_index(self, int size, bint signed=True):
        """读取索引值

        Args:
            size: 索引字节数 (1, 2, 或 4)
            signed: 是否有符号

        Returns:
            索引值
        """
        if size == 1:
            if signed:
                return self.read_sbyte()
            else:
                return self.read_byte()
        elif size == 2:
            if signed:
                return self.read_short()
            else:
                return self.read_ushort()
        else:  # size == 4
            if signed:
                return self.read_int()
            else:
                return self.read_uint()


# 四元数到欧拉角转换 (Cython优化)
cpdef tuple quaternion_to_euler_fast(double qx, double qy, double qz, double qw):
    """将四元数转换为欧拉角 (度)

    Args:
        qx, qy, qz, qw: 四元数分量

    Returns:
        (roll, pitch, yaw) 欧拉角 (度)
    """
    cdef double sinr_cosp, cosr_cosp, sinp, siny_cosp, cosy_cosp
    cdef double roll, pitch, yaw

    # Roll (x-axis rotation)
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    roll = atan2(sinr_cosp, cosr_cosp)

    # Pitch (y-axis rotation)
    sinp = 2.0 * (qw * qy - qz * qx)
    if sinp >= 1.0:
        pitch = M_PI / 2.0
    elif sinp <= -1.0:
        pitch = -M_PI / 2.0
    else:
        pitch = asin(sinp)

    # Yaw (z-axis rotation)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw = atan2(siny_cosp, cosy_cosp)

    # 转换为度
    return (roll * RAD_TO_DEG, pitch * RAD_TO_DEG, yaw * RAD_TO_DEG)


cpdef tuple euler_to_quaternion_fast(double roll_deg, double pitch_deg, double yaw_deg):
    """将欧拉角转换为四元数

    Args:
        roll_deg, pitch_deg, yaw_deg: 欧拉角 (度)

    Returns:
        (qw, qx, qy, qz) 四元数
    """
    cdef double roll = roll_deg / RAD_TO_DEG
    cdef double pitch = pitch_deg / RAD_TO_DEG
    cdef double yaw = yaw_deg / RAD_TO_DEG

    cdef double cy = cos(yaw * 0.5)
    cdef double sy = sin(yaw * 0.5)
    cdef double cp = cos(pitch * 0.5)
    cdef double sp = sin(pitch * 0.5)
    cdef double cr = cos(roll * 0.5)
    cdef double sr = sin(roll * 0.5)

    cdef double w = cr * cp * cy + sr * sp * sy
    cdef double x = sr * cp * cy - cr * sp * sy
    cdef double y = cr * sp * cy + sr * cp * sy
    cdef double z = cr * cp * sy - sr * sp * cy

    return (w, x, y, z)

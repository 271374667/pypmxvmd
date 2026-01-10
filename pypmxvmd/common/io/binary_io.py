"""
PyPMXVMD 二进制I/O操作模块

提供二进制文件读写和数据打包/解包功能。
支持MMD文件格式的特殊编码需求。

性能优化版本：
- 使用偏移量追踪而非切片删除 (O(1) vs O(n))
- 预编译struct格式字符串
- memoryview避免数据拷贝
"""

import struct
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Tuple, Union


class BinaryIOHandler:
    """二进制I/O处理器

    负责二进制文件的读写操作和数据的打包解包。
    支持多种数据类型和编码格式。

    性能优化：
    - 使用偏移量追踪位置而非修改bytearray
    - 缓存预编译的struct对象
    - 支持memoryview高效读取
    """

    # 预编译常用struct格式（类级别缓存）
    _struct_cache: Dict[str, struct.Struct] = {}

    def __init__(self, encoding: str = "shift_jis"):
        """初始化二进制I/O处理器

        Args:
            encoding: 字符串编码格式，默认为shift_jis
        """
        self._encoding = encoding
        self._file_handle: BinaryIO = None
        self._position = 0
        # 新增：数据缓冲区和memoryview
        self._data: bytes = b''
        self._view: memoryview = None

    @classmethod
    def _get_struct(cls, format_string: str) -> struct.Struct:
        """获取预编译的struct对象（带缓存）"""
        if format_string not in cls._struct_cache:
            cls._struct_cache[format_string] = struct.Struct(format_string)
        return cls._struct_cache[format_string]

    def set_encoding(self, encoding: str) -> None:
        """设置字符串编码格式

        Args:
            encoding: 新的编码格式
        """
        self._encoding = encoding

    def read_file(self, file_path: Union[str, Path]) -> bytearray:
        """读取二进制文件内容

        Args:
            file_path: 文件路径

        Returns:
            文件内容的字节数组（为了兼容性）

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 读取失败
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            with open(file_path, 'rb') as f:
                self._data = f.read()
            # 重置位置并创建memoryview
            self._position = 0
            self._view = memoryview(self._data)
            # 返回bytearray以保持API兼容性
            return bytearray(self._data)
        except IOError as e:
            raise IOError(f"读取文件失败: {file_path}, 错误: {e}")

    def read_file_fast(self, file_path: Union[str, Path]) -> None:
        """快速读取文件（不返回bytearray，直接使用内部缓冲区）

        这是性能优化的读取方式，避免创建额外的bytearray拷贝。
        读取后使用 unpack_from_buffer / read_string_from_buffer 等方法访问数据。

        Args:
            file_path: 文件路径

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 读取失败
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            with open(file_path, 'rb') as f:
                self._data = f.read()
            self._position = 0
            self._view = memoryview(self._data)
        except IOError as e:
            raise IOError(f"读取文件失败: {file_path}, 错误: {e}")

    def write_file(self, file_path: Union[str, Path], data: bytes) -> None:
        """写入二进制文件

        Args:
            file_path: 文件路径
            data: 要写入的字节数据

        Raises:
            IOError: 写入失败
        """
        file_path = Path(file_path)
        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'wb') as f:
                f.write(data)
        except IOError as e:
            raise IOError(f"写入文件失败: {file_path}, 错误: {e}")

    def unpack_data(self, format_string: str, data: bytearray) -> Tuple[Any, ...]:
        """解包二进制数据（兼容旧API）

        Args:
            format_string: struct格式字符串
            data: 要解包的数据

        Returns:
            解包后的数据元组
        """
        # 使用传统方式（兼容性）- 不使用内部缓冲区
        try:
            s = self._get_struct(format_string)
            size = s.size
            if len(data) < size:
                raise ValueError(f"数据长度不足，需要{size}字节，实际{len(data)}字节")

            result = s.unpack_from(data, 0)
            # 更新数据位置
            del data[:size]
            self._position += size

            return result
        except struct.error as e:
            raise ValueError(f"解包数据失败: {e}")

    def unpack_from_buffer(self, format_string: str) -> Tuple[Any, ...]:
        """从内部缓冲区解包数据（高性能版本）

        使用内部memoryview直接读取，避免切片删除操作。
        这是 O(1) 操作，相比 unpack_data 的 O(n) 大幅提升性能。

        Args:
            format_string: struct格式字符串

        Returns:
            解包后的数据元组
        """
        if self._view is None:
            raise RuntimeError("未初始化内部缓冲区，请先调用 read_file_fast()")

        try:
            s = self._get_struct(format_string)
            size = s.size
            if self._position + size > len(self._data):
                raise ValueError(f"数据长度不足，需要{size}字节，剩余{len(self._data) - self._position}字节")

            result = s.unpack_from(self._data, self._position)
            self._position += size
            return result
        except struct.error as e:
            raise ValueError(f"解包数据失败: {e}")

    def pack_data(self, format_string: str, *values) -> bytes:
        """打包数据为二进制格式

        Args:
            format_string: struct格式字符串
            *values: 要打包的值

        Returns:
            打包后的二进制数据
        """
        try:
            s = self._get_struct(format_string)
            return s.pack(*values)
        except struct.error as e:
            raise ValueError(f"打包数据失败: {e}")

    def read_string(self, data: bytearray, length: int,
                   null_terminated: bool = True) -> str:
        """从二进制数据中读取字符串（兼容旧API）

        Args:
            data: 二进制数据
            length: 字符串长度（字节数）
            null_terminated: 是否以null结尾

        Returns:
            解码后的字符串
        """
        # 使用传统方式（兼容性）- 不使用内部缓冲区
        if len(data) < length:
            raise ValueError(f"数据长度不足，需要{length}字节，实际{len(data)}字节")

        string_bytes = bytes(data[:length])
        del data[:length]
        self._position += length

        # 如果是null结尾的字符串，截断至第一个null字符
        if null_terminated:
            null_pos = string_bytes.find(b'\x00')
            if null_pos != -1:
                string_bytes = string_bytes[:null_pos]

        # 处理编码错误
        try:
            return string_bytes.decode(self._encoding)
        except UnicodeDecodeError:
            return string_bytes.decode(self._encoding, errors='ignore')

    def read_string_from_buffer(self, length: int,
                                null_terminated: bool = True) -> str:
        """从内部缓冲区读取字符串（高性能版本）

        Args:
            length: 字符串长度（字节数）
            null_terminated: 是否以null结尾

        Returns:
            解码后的字符串
        """
        if self._view is None:
            raise RuntimeError("未初始化内部缓冲区，请先调用 read_file_fast()")

        if self._position + length > len(self._data):
            raise ValueError(f"数据长度不足，需要{length}字节，剩余{len(self._data) - self._position}字节")

        # 直接从bytes切片（不修改原数据）
        string_bytes = self._data[self._position:self._position + length]
        self._position += length

        # 如果是null结尾的字符串，截断至第一个null字符
        if null_terminated:
            null_pos = string_bytes.find(b'\x00')
            if null_pos != -1:
                string_bytes = string_bytes[:null_pos]

        # 处理编码错误
        try:
            return string_bytes.decode(self._encoding)
        except UnicodeDecodeError:
            return string_bytes.decode(self._encoding, errors='ignore')

    def write_string(self, text: str, length: int,
                    null_terminated: bool = True) -> bytes:
        """将字符串编码为指定长度的二进制数据

        Args:
            text: 要编码的字符串
            length: 目标长度（字节数）
            null_terminated: 是否添加null结尾

        Returns:
            编码后的二进制数据
        """
        # 编码字符串
        try:
            encoded = text.encode(self._encoding)
        except UnicodeEncodeError:
            # 如果编码失败，使用错误处理策略
            encoded = text.encode(self._encoding, errors='ignore')

        # 截断或填充到指定长度
        if len(encoded) > length:
            encoded = encoded[:length]

        # 添加null结尾（如果需要且有空间）
        if null_terminated and len(encoded) < length:
            encoded += b'\x00'

        # 用零填充到指定长度
        if len(encoded) < length:
            encoded += b'\x00' * (length - len(encoded))

        return encoded

    def read_variable_string(self, data: bytearray) -> str:
        """读取可变长度字符串（前缀长度）（兼容旧API）

        PMX等格式使用的变长字符串格式：
        - 前4字节为字符串长度
        - 后续为字符串内容

        Args:
            data: 二进制数据

        Returns:
            解码后的字符串
        """
        # 使用传统方式（兼容性）- 不使用内部缓冲区
        # 读取长度
        if len(data) < 4:
            raise ValueError("数据不足以读取字符串长度")

        length = struct.unpack('<I', data[:4])[0]
        del data[:4]
        self._position += 4

        # 读取字符串内容
        if len(data) < length:
            raise ValueError(f"数据不足以读取字符串内容，需要{length}字节")

        string_bytes = bytes(data[:length])
        del data[:length]
        self._position += length

        # 根据编码格式解码
        try:
            if self._encoding.lower() in ('utf-8', 'utf8'):
                return string_bytes.decode('utf-8')
            elif self._encoding.lower() in ('utf-16', 'utf16', 'utf-16le'):
                return string_bytes.decode('utf-16le')
            else:
                return string_bytes.decode(self._encoding)
        except UnicodeDecodeError:
            return string_bytes.decode(self._encoding, errors='ignore')

    def read_variable_string_from_buffer(self) -> str:
        """从内部缓冲区读取可变长度字符串（高性能版本）

        Returns:
            解码后的字符串
        """
        if self._view is None:
            raise RuntimeError("未初始化内部缓冲区，请先调用 read_file_fast()")

        # 读取长度
        if self._position + 4 > len(self._data):
            raise ValueError("数据不足以读取字符串长度")

        length = struct.unpack_from('<I', self._data, self._position)[0]
        self._position += 4

        # 读取字符串内容
        if self._position + length > len(self._data):
            raise ValueError(f"数据不足以读取字符串内容，需要{length}字节")

        string_bytes = self._data[self._position:self._position + length]
        self._position += length

        # 根据编码格式解码
        try:
            if self._encoding.lower() in ('utf-8', 'utf8'):
                return string_bytes.decode('utf-8')
            elif self._encoding.lower() in ('utf-16', 'utf16', 'utf-16le'):
                return string_bytes.decode('utf-16le')
            else:
                return string_bytes.decode(self._encoding)
        except UnicodeDecodeError:
            return string_bytes.decode(self._encoding, errors='ignore')

    def write_variable_string(self, text: str) -> bytes:
        """写入可变长度字符串

        Args:
            text: 要写入的字符串

        Returns:
            编码后的二进制数据（长度+内容）
        """
        # 根据编码格式编码字符串
        try:
            if self._encoding.lower() in ('utf-8', 'utf8'):
                encoded = text.encode('utf-8')
            elif self._encoding.lower() in ('utf-16', 'utf16', 'utf-16le'):
                encoded = text.encode('utf-16le')
            else:
                encoded = text.encode(self._encoding)
        except UnicodeEncodeError:
            encoded = text.encode(self._encoding, errors='ignore')

        # 打包长度和内容
        length_bytes = struct.pack('<I', len(encoded))
        return length_bytes + encoded

    def get_position(self) -> int:
        """获取当前读取位置"""
        return self._position

    def reset_position(self) -> None:
        """重置读取位置"""
        self._position = 0

    def set_position(self, position: int) -> None:
        """设置读取位置

        Args:
            position: 新的读取位置
        """
        if position < 0:
            raise ValueError("位置不能为负数")
        self._position = position

    def get_remaining_size(self) -> int:
        """获取剩余可读取的字节数"""
        if self._data:
            return len(self._data) - self._position
        return 0

    def get_total_size(self) -> int:
        """获取数据总大小"""
        return len(self._data) if self._data else 0

    def skip_bytes(self, count: int) -> None:
        """跳过指定字节数

        Args:
            count: 要跳过的字节数
        """
        if count < 0:
            raise ValueError("跳过的字节数不能为负数")
        self._position += count

    def peek_bytes(self, count: int) -> bytes:
        """预览指定字节数的数据（不移动位置）

        Args:
            count: 要预览的字节数

        Returns:
            预览的字节数据
        """
        if self._data is None:
            raise RuntimeError("未初始化内部缓冲区")
        if self._position + count > len(self._data):
            raise ValueError(f"数据长度不足，需要{count}字节")
        return self._data[self._position:self._position + count]

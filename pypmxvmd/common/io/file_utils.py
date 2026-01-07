"""
PyPMXVMD 文件工具模块

提供文件和路径相关的实用工具函数。
包含文件操作、路径处理、备份管理等功能。
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Union, Tuple
import re


class FileUtils:
    """文件工具类
    
    提供文件操作的静态方法集合。
    """
    
    @staticmethod
    def ensure_directory(directory_path: Union[str, Path]) -> Path:
        """确保目录存在，如果不存在则创建
        
        Args:
            directory_path: 目录路径
            
        Returns:
            目录路径对象
        """
        directory_path = Path(directory_path)
        directory_path.mkdir(parents=True, exist_ok=True)
        return directory_path
    
    @staticmethod
    def get_unused_filename(file_path: Union[str, Path], 
                           max_attempts: int = 1000) -> Path:
        """获取一个不存在的文件名
        
        如果文件已存在，在文件名后添加数字后缀。
        
        Args:
            file_path: 原始文件路径
            max_attempts: 最大尝试次数
            
        Returns:
            不存在的文件路径
            
        Raises:
            RuntimeError: 超过最大尝试次数仍未找到可用文件名
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return file_path
        
        # 分离文件名和扩展名
        stem = file_path.stem
        suffix = file_path.suffix
        parent = file_path.parent
        
        for i in range(1, max_attempts + 1):
            new_name = f"{stem}_{i:03d}{suffix}"
            new_path = parent / new_name
            
            if not new_path.exists():
                return new_path
        
        raise RuntimeError(f"无法找到可用的文件名，已尝试 {max_attempts} 次")
    
    @staticmethod
    def add_suffix_to_filename(file_path: Union[str, Path], 
                              suffix: str) -> Path:
        """在文件名中添加后缀
        
        Args:
            file_path: 原始文件路径
            suffix: 要添加的后缀
            
        Returns:
            添加后缀后的文件路径
        """
        file_path = Path(file_path)
        stem = file_path.stem
        extension = file_path.suffix
        parent = file_path.parent
        
        new_name = f"{stem}{suffix}{extension}"
        return parent / new_name
    
    @staticmethod
    def backup_file(file_path: Union[str, Path], 
                   backup_suffix: str = "_backup") -> Optional[Path]:
        """备份文件
        
        Args:
            file_path: 要备份的文件路径
            backup_suffix: 备份文件后缀
            
        Returns:
            备份文件路径，如果原文件不存在返回None
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return None
        
        backup_path = FileUtils.add_suffix_to_filename(file_path, backup_suffix)
        backup_path = FileUtils.get_unused_filename(backup_path)
        
        try:
            shutil.copy2(file_path, backup_path)
            return backup_path
        except IOError as e:
            print(f"警告: 备份文件失败: {e}")
            return None
    
    @staticmethod
    def is_valid_filename(filename: str) -> bool:
        """检查文件名是否有效
        
        Args:
            filename: 文件名
            
        Returns:
            文件名有效返回True
        """
        # Windows文件名禁用字符
        invalid_chars = r'[<>:"/\\|?*]'
        
        # 检查是否包含无效字符
        if re.search(invalid_chars, filename):
            return False
        
        # 检查是否为Windows保留名称
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        
        name_without_ext = Path(filename).stem.upper()
        if name_without_ext in reserved_names:
            return False
        
        # 检查文件名长度
        if len(filename) > 255:
            return False
        
        return True
    
    @staticmethod
    def sanitize_filename(filename: str, replacement: str = "_") -> str:
        """清理文件名，替换无效字符
        
        Args:
            filename: 原始文件名
            replacement: 替换字符
            
        Returns:
            清理后的文件名
        """
        # 替换无效字符
        invalid_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(invalid_chars, replacement, filename)
        
        # 移除控制字符
        sanitized = re.sub(r'[\x00-\x1f\x7f]', replacement, sanitized)
        
        # 截断过长的文件名
        if len(sanitized) > 255:
            path_obj = Path(sanitized)
            stem = path_obj.stem[:200]  # 保留扩展名的空间
            suffix = path_obj.suffix
            sanitized = stem + suffix
        
        return sanitized
    
    @staticmethod
    def get_relative_path(file_path: Union[str, Path], 
                         base_path: Union[str, Path]) -> Path:
        """获取相对于基准路径的相对路径
        
        Args:
            file_path: 文件路径
            base_path: 基准路径
            
        Returns:
            相对路径
        """
        file_path = Path(file_path).absolute()
        base_path = Path(base_path).absolute()
        
        try:
            return file_path.relative_to(base_path)
        except ValueError:
            # 如果无法计算相对路径，返回绝对路径
            return file_path
    
    @staticmethod
    def find_files(directory: Union[str, Path], 
                  pattern: str = "*",
                  recursive: bool = True) -> List[Path]:
        """在目录中查找文件
        
        Args:
            directory: 搜索目录
            pattern: 文件名模式（支持通配符）
            recursive: 是否递归搜索子目录
            
        Returns:
            找到的文件路径列表
        """
        directory = Path(directory)
        
        if not directory.exists() or not directory.is_dir():
            return []
        
        if recursive:
            return list(directory.rglob(pattern))
        else:
            return list(directory.glob(pattern))
    
    @staticmethod
    def get_file_size_str(file_path: Union[str, Path]) -> str:
        """获取文件大小的可读字符串
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件大小字符串（如"1.5 MB"）
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return "文件不存在"
        
        size_bytes = file_path.stat().st_size
        
        # 单位转换
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        size = float(size_bytes)
        unit_index = 0
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.2f} {units[unit_index]}"
    
    @staticmethod
    def is_texture_file(file_path: Union[str, Path]) -> bool:
        """判断是否为纹理文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是纹理文件返回True
        """
        texture_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.gif'}
        file_path = Path(file_path)
        return file_path.suffix.lower() in texture_extensions
    
    @staticmethod
    def is_mmd_file(file_path: Union[str, Path]) -> Tuple[bool, str]:
        """判断是否为MMD相关文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            元组 (是否为MMD文件, 文件类型)
        """
        file_path = Path(file_path)
        extension = file_path.suffix.lower()
        
        mmd_extensions = {
            '.pmx': 'PMX模型',
            '.pmd': 'PMD模型',
            '.vmd': 'VMD动作',
            '.vpd': 'VPD姿势',
            '.x': 'X模型'
        }
        
        if extension in mmd_extensions:
            return True, mmd_extensions[extension]
        
        return False, "未知"
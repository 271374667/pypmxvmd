"""
PyPMXVMD 文本I/O操作模块

提供文本文件读写功能，支持多种编码格式。
主要用于VPD文件和VMD文本转换功能。
"""

import csv
from pathlib import Path
from typing import Any, List, Dict, Union, TextIO


class TextIOHandler:
    """文本I/O处理器
    
    负责文本文件的读写操作，支持不同编码格式。
    提供CSV读写和结构化文本处理功能。
    """
    
    def __init__(self, encoding: str = "utf-8"):
        """初始化文本I/O处理器
        
        Args:
            encoding: 文本编码格式，默认为utf-8
        """
        self._encoding = encoding
    
    def set_encoding(self, encoding: str) -> None:
        """设置文本编码格式
        
        Args:
            encoding: 新的编码格式
        """
        self._encoding = encoding
    
    def read_file(self, file_path: Union[str, Path]) -> str:
        """读取文本文件内容
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容字符串
            
        Raises:
            FileNotFoundError: 文件不存在
            IOError: 读取失败
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        try:
            with open(file_path, 'r', encoding=self._encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码格式
            encodings = ['utf-8', 'shift_jis', 'gbk', 'latin1']
            for enc in encodings:
                if enc == self._encoding:
                    continue
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        content = f.read()
                        print(f"警告: 使用 {enc} 编码读取文件 {file_path}")
                        return content
                except UnicodeDecodeError:
                    continue
            raise IOError(f"无法解码文件: {file_path}")
        except IOError as e:
            raise IOError(f"读取文件失败: {file_path}, 错误: {e}")
    
    def write_file(self, file_path: Union[str, Path], content: str) -> None:
        """写入文本文件
        
        Args:
            file_path: 文件路径
            content: 要写入的内容
            
        Raises:
            IOError: 写入失败
        """
        file_path = Path(file_path)
        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding=self._encoding) as f:
                f.write(content)
        except IOError as e:
            raise IOError(f"写入文件失败: {file_path}, 错误: {e}")
    
    def read_lines(self, file_path: Union[str, Path], 
                  strip_whitespace: bool = True) -> List[str]:
        """读取文本文件并分割为行
        
        Args:
            file_path: 文件路径
            strip_whitespace: 是否移除行首尾空白字符
            
        Returns:
            文件内容行列表
        """
        content = self.read_file(file_path)
        lines = content.splitlines()
        
        if strip_whitespace:
            lines = [line.strip() for line in lines]
            
        return lines
    
    def write_lines(self, file_path: Union[str, Path], lines: List[str]) -> None:
        """写入行列表到文本文件
        
        Args:
            file_path: 文件路径
            lines: 要写入的行列表
        """
        content = '\n'.join(lines)
        self.write_file(file_path, content)
    
    def read_csv(self, file_path: Union[str, Path], 
                delimiter: str = ',', has_header: bool = False) -> List[List[str]]:
        """读取CSV文件
        
        Args:
            file_path: 文件路径
            delimiter: 分隔符
            has_header: 是否有头行
            
        Returns:
            CSV数据列表
        """
        file_path = Path(file_path)
        try:
            with open(file_path, 'r', encoding=self._encoding, newline='') as f:
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
                
                if has_header and rows:
                    return rows[1:]  # 跳过头行
                return rows
        except IOError as e:
            raise IOError(f"读取CSV文件失败: {file_path}, 错误: {e}")
    
    def write_csv(self, file_path: Union[str, Path], data: List[List[str]], 
                 delimiter: str = ',', header: List[str] = None) -> None:
        """写入CSV文件
        
        Args:
            file_path: 文件路径
            data: CSV数据
            delimiter: 分隔符
            header: 可选的头行
        """
        file_path = Path(file_path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding=self._encoding, 
                     newline='') as f:
                writer = csv.writer(f, delimiter=delimiter)
                
                if header:
                    writer.writerow(header)
                writer.writerows(data)
        except IOError as e:
            raise IOError(f"写入CSV文件失败: {file_path}, 错误: {e}")
    
    def parse_vpd_content(self, content: str) -> Dict[str, Any]:
        """解析VPD文件内容
        
        VPD文件是结构化的文本格式，包含骨骼和变形数据。
        
        Args:
            content: VPD文件内容
            
        Returns:
            解析后的数据字典
        """
        lines = content.splitlines()
        data = {
            'model_name': '',
            'bone_count': 0,
            'bones': [],
            'morph_count': 0,
            'morphs': []
        }
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 跳过空行和注释
            if not line or line.startswith(';'):
                i += 1
                continue
            
            # 解析模型名称
            if line.startswith('Vocaloid Pose Data file'):
                i += 1
                if i < len(lines):
                    data['model_name'] = lines[i].strip().rstrip(';')
                i += 1
                continue
            
            # 解析骨骼数量
            if line.endswith('//') and ',' not in line:
                try:
                    data['bone_count'] = int(line.replace('//', '').strip())
                    i += 1
                    continue
                except ValueError:
                    pass
            
            # 解析骨骼数据
            if line.startswith('Bone') and '{' in line:
                bone_name = line.split('{')[0].replace('Bone', '').strip()
                i += 1
                
                position = [0.0, 0.0, 0.0]
                rotation = [0.0, 0.0, 0.0, 1.0]
                
                # 读取骨骼数据
                while i < len(lines) and '}' not in lines[i]:
                    data_line = lines[i].strip()
                    if data_line and not data_line.startswith('//'):
                        parts = data_line.rstrip(';').split(',')
                        if len(parts) >= 7:
                            try:
                                position = [float(parts[0]), float(parts[1]), float(parts[2])]
                                rotation = [float(parts[3]), float(parts[4]), 
                                          float(parts[5]), float(parts[6])]
                            except ValueError:
                                pass
                    i += 1
                
                data['bones'].append({
                    'name': bone_name,
                    'position': position,
                    'rotation': rotation
                })
                i += 1
                continue
            
            # 解析变形数量和数据 (简化处理)
            if 'Expression' in line or 'Morph' in line:
                # 这里可以添加变形数据的解析逻辑
                pass
            
            i += 1
        
        return data
    
    def format_vpd_content(self, data: Dict[str, Any]) -> str:
        """格式化VPD文件内容
        
        Args:
            data: VPD数据字典
            
        Returns:
            格式化后的VPD文件内容
        """
        lines = []
        
        # 文件头
        lines.append('Vocaloid Pose Data file')
        lines.append('')
        lines.append(f'{data.get("model_name", "")};')
        lines.append(f'{len(data.get("bones", []))};')
        lines.append('')
        
        # 骨骼数据
        for bone in data.get('bones', []):
            lines.append(f'Bone{bone["name"]}{{')
            pos = bone['position']
            rot = bone['rotation']
            lines.append(f'  {pos[0]:.6f},{pos[1]:.6f},{pos[2]:.6f},'
                        f'{rot[0]:.6f},{rot[1]:.6f},{rot[2]:.6f},{rot[3]:.6f};')
            lines.append('}')
            lines.append('')
        
        # 变形数据 (如果有)
        morphs = data.get('morphs', [])
        if morphs:
            lines.append(f'{len(morphs)};')
            lines.append('')
            
            for morph in morphs:
                lines.append(f'Expression{morph["name"]}{{')
                lines.append(f'  {morph["weight"]:.6f};')
                lines.append('}')
                lines.append('')
        else:
            lines.append('0;')
        
        return '\n'.join(lines)
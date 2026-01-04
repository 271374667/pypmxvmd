"""
PyMMD 基础数据模型

定义所有数据模型的抽象基类和通用功能。
提供验证、复制、序列化等基础能力。
"""

import abc
import copy
import sys
import traceback
from typing import Any, List, Optional, Union


class BaseModel(abc.ABC):
    """所有MMD数据模型的抽象基类
    
    提供数据验证、对象比较、深拷贝等通用功能。
    所有具体的数据模型类都应该继承此基类。
    
    Attributes:
        _validated: 是否已通过验证的标志位
    """
    
    def __init__(self):
        """初始化基础模型"""
        self._validated: bool = False
    
    def copy(self) -> "BaseModel":
        """创建对象的深拷贝
        
        Returns:
            返回当前对象的深拷贝副本
        """
        return copy.deepcopy(self)
    
    @abc.abstractmethod
    def to_list(self) -> List[Any]:
        """将对象转换为列表格式
        
        子类必须实现此方法，用于调试和序列化。
        
        Returns:
            对象的列表表示
        """
        pass
    
    @abc.abstractmethod 
    def _validate_data(self, parent_list: Optional[List] = None) -> None:
        """验证数据的具体实现
        
        子类必须实现此方法，包含具体的验证逻辑。
        如果验证失败应该抛出AssertionError或ValueError。
        
        Args:
            parent_list: 如果对象属于某个列表，传入该列表用于错误报告
            
        Raises:
            AssertionError: 数据验证失败
            ValueError: 数据类型错误
        """
        pass
    
    def validate(self, parent_list: Optional[List] = None) -> bool:
        """验证对象数据的有效性
        
        执行类型检查和数据验证，防止无效数据破坏结构。
        验证失败会抛出异常并打印详细的错误信息。
        
        Args:
            parent_list: 如果对象属于某个列表，传入该列表用于错误报告
            
        Returns:
            验证成功返回True
            
        Raises:
            RuntimeError: 验证失败
        """
        try:
            # 执行具体的验证逻辑
            self._validate_data(parent_list)
            self._validated = True
            return True
        except (AssertionError, ValueError) as e:
            # 处理验证错误
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback_info = traceback.extract_tb(exc_traceback, limit=None)
            
            # 获取最底层的错误信息
            lowest_trace = traceback_info[-1]
            print(f'数据验证错误: 对象 "{self.__class__.__name__}" '
                  f'在第 "{lowest_trace.lineno}" 行验证检查 "{lowest_trace.line}" 失败')
            print("这通常是由于数据大小/类型不正确导致的。")
            print("请检查数据来源，确保数据的正确性！")
            
            # 如果属于某个列表，报告其在列表中的索引
            if parent_list is not None:
                idx = self._find_index_in_list(parent_list)
                if idx is not None:
                    print(f'对象 {self.__class__.__name__} 位于列表索引 {idx} 处')
            
            raise RuntimeError("数据验证失败") from e
        except RuntimeError:
            # 重新抛出运行时错误
            if parent_list is not None:
                idx = self._find_index_in_list(parent_list)
                if idx is not None:
                    print(f'对象 {self.__class__.__name__} 位于列表索引 {idx} 处')
            raise
    
    def _find_index_in_list(self, target_list: List) -> Optional[int]:
        """在列表中查找当前对象的索引
        
        Args:
            target_list: 要搜索的列表
            
        Returns:
            找到返回索引，否则返回None
        """
        for i, item in enumerate(target_list):
            if self is item:
                return i
        return None
    
    def __str__(self) -> str:
        """字符串表示，用于调试"""
        return str(self.to_list())
    
    def __eq__(self, other: Any) -> bool:
        """对象相等比较"""
        if type(self) != type(other):
            return False
        return self.to_list() == other.to_list()
    
    def __repr__(self) -> str:
        """对象的正式字符串表示"""
        return f"{self.__class__.__name__}({self.to_list()})"


def is_valid_vector(length: int, data: Any) -> bool:
    """验证向量数据的有效性
    
    检查数据是否为指定长度的数值列表。
    
    Args:
        length: 期望的向量长度
        data: 要验证的数据
        
    Returns:
        数据有效返回True，否则返回False
    """
    return (isinstance(data, (list, tuple)) and 
            len(data) == length and 
            all(isinstance(x, (int, float)) for x in data))


def is_valid_flag(data: Any) -> bool:
    """验证标志位数据的有效性
    
    检查数据是否为有效的布尔值或0/1整数。
    
    Args:
        data: 要验证的数据
        
    Returns:
        数据有效返回True，否则返回False  
    """
    return isinstance(data, (bool, int)) and data in (0, 1, True, False)
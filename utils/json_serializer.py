"""
JSON 序列化工具模块

处理包含复杂对象的 JSON 序列化，特别是 llama-index 的 Node 对象
"""
import json
from typing import Any, Dict, Union


def make_json_serializable(obj: Any) -> Any:
    """
    将对象转换为 JSON 可序列化的格式

    处理 llama-index 中的特殊对象，如 RelatedNodeInfo 等
    特别处理 relationships 字典，确保键是正确的枚举格式

    Args:
        obj: 要转换的对象

    Returns:
        JSON 可序列化的对象
    """
    if obj is None:
        return None

    # 基本类型直接返回
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # 列表和元组递归处理
    if isinstance(obj, (list, tuple)):
        return [make_json_serializable(item) for item in obj]

    # 特殊处理：relationships 字典
    if isinstance(obj, dict) and any('Relationship' in str(key) for key in obj.keys()):
        return make_relationships_serializable(obj)

    # 普通字典递归处理值
    if isinstance(obj, dict):
        return {str(key): make_json_serializable(value) for key, value in obj.items()}

    # 处理 llama-index 的特殊对象
    obj_class_name = obj.__class__.__name__

    if obj_class_name == 'RelatedNodeInfo':
        # RelatedNodeInfo 对象转换为字典
        return {
            'class_name': 'RelatedNodeInfo',
            'node_id': getattr(obj, 'node_id', None),
            'node_type': getattr(obj, 'node_type', None),
            'metadata': make_json_serializable(getattr(obj, 'metadata', {})),
            'hash': getattr(obj, 'hash', None),
        }

    if obj_class_name == 'NodeRelationship':
        # NodeRelationship 对象转换为字典
        return {
            'class_name': 'NodeRelationship',
            'source_node_id': getattr(obj, 'source_node_id', None),
            'target_node_id': getattr(obj, 'target_node_id', None),
            'relationship_type': getattr(obj, 'relationship_type', None),
        }

    # 处理其他 llama-index 对象
    if hasattr(obj, '__dict__'):
        # 有 __dict__ 的对象，提取其属性
        result = {'class_name': obj_class_name}
        for key, value in obj.__dict__.items():
            # 跳过私有属性和方法
            if not key.startswith('_') and not callable(value):
                result[key] = make_json_serializable(value)
        return result

    # 处理可迭代对象（不包括字符串）
    try:
        if hasattr(obj, '__iter__') and not isinstance(obj, str):
            return [make_json_serializable(item) for item in obj]
    except:
        pass

    # 最后手段：转换为字符串
    return str(obj)


def make_relationships_serializable(relationships_dict: Dict[Any, Any]) -> Dict[str, Any]:
    """
    将 relationships 字典转换为可序列化的格式

    处理 llama-index 的 relationships 字典，将枚举键转换为枚举值（'1', '2', '3', '4', '5'），
    以便 TextNode 能够正确反序列化

    Args:
        relationships_dict: 原始 relationships 字典

    Returns:
        可序列化的 relationships 字典，键为枚举值（'1', '2', '3', '4', '5'）
    """
    result = {}

    for key, value in relationships_dict.items():
        # 将枚举键转换为枚举值（如 NodeRelationship.SOURCE -> "1"）
        if hasattr(key, 'value'):
            # 如果是枚举对象，使用 value 属性
            key_str = str(key.value)
        else:
            # 如果已经是字符串，直接使用
            key_str = str(key)

        # 处理值（RelatedNodeInfo 对象或列表）
        if isinstance(value, list):
            # 如果是列表，递归处理每个元素
            result[key_str] = [make_json_serializable(item) for item in value]
        else:
            # 单个值
            result[key_str] = make_json_serializable(value)

    return result

def safe_json_dumps(obj: Any, **kwargs) -> str:
    """
    安全的 JSON 序列化函数

    自动处理不可序列化的对象，特别确保 relationships 字典被正确处理

    Args:
        obj: 要序列化的对象
        **kwargs: 传递给 json.dumps 的其他参数

    Returns:
        JSON 字符串
    """
    # 先处理对象，确保 relationships 等特殊字段被正确转换
    processed_obj = make_json_serializable(obj)

    try:
        # 序列化处理后的对象
        return json.dumps(processed_obj, **kwargs)
    except TypeError as e:
        # 如果仍有不可序列化的部分，再次处理
        final_obj = make_json_serializable(processed_obj)
        return json.dumps(final_obj, **kwargs)


def safe_json_loads(json_str: str, **kwargs) -> Any:
    """
    安全的 JSON 反序列化函数

    Args:
        json_str: JSON 字符串
        **kwargs: 传递给 json.loads 的其他参数

    Returns:
        反序列化后的对象
    """
    return json.loads(json_str, **kwargs)
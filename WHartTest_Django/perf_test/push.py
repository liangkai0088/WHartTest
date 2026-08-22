"""性能测试实时推送辅助：通过 Channels 向 WebSocket 客户端广播执行进度。"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

GROUP_PREFIX = 'perf_test_execution_'


def _group_name(execution_id):
    return f"{GROUP_PREFIX}{execution_id}"


def push_execution_update(execution_id, payload):
    """向指定执行记录对应的 WebSocket 组广播一次更新。"""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            _group_name(execution_id),
            {'type': 'perf_test.update', 'data': payload},
        )
    except Exception as exc:
        logger.warning(f"推送压测进度失败 execution={execution_id}: {exc}")

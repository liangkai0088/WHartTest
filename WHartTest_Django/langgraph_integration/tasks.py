"""LangGraph 集成周期任务"""

import logging
import os
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from wharttest_django.checkpointer import (
    delete_checkpoints_by_thread_id,
    get_database_type,
    get_db_connection_string,
)
from .models import ChatSession

logger = logging.getLogger(__name__)


@shared_task(name='langgraph_integration.tasks.cleanup_langgraph_checkpoints')
def cleanup_langgraph_checkpoints():
    """清理超过保留天数未更新的对话会话及其 LangGraph checkpoints，默认保留 60 天。"""
    try:
        retention_days = max(int(os.environ.get('CHECKPOINT_RETENTION_DAYS', '60') or 60), 1)
    except (TypeError, ValueError):
        retention_days = 60
    cutoff_time = timezone.now() - timedelta(days=retention_days)

    stale_qs = ChatSession.objects.filter(updated_at__lt=cutoff_time)

    removed_checkpoints = 0
    session_pks = []
    skipped_null_project = 0
    for session in stale_qs.iterator():
        # project_id 为空时无法还原 thread_id（user_id_project_id_session_id），跳过
        if session.project_id is None:
            skipped_null_project += 1
            logger.warning(
                '跳过清理 project_id 为空的历史会话: session_id=%s, user_id=%s',
                session.session_id,
                session.user_id,
            )
            continue

        thread_id = f"{session.user_id}_{session.project_id}_{session.session_id}"
        try:
            removed_checkpoints += delete_checkpoints_by_thread_id(thread_id)
        except Exception as exc:
            logger.error(
                '删除 LangGraph checkpoints 失败: thread_id=%s, error=%s',
                thread_id,
                exc,
                exc_info=True,
            )
        session_pks.append(session.pk)

    deleted_sessions = 0
    deleted_rows = 0
    if session_pks:
        # 级联删除关联的 ChatMessage
        deleted_rows, per_model = ChatSession.objects.filter(pk__in=session_pks).delete()
        deleted_sessions = per_model.get('langgraph_integration.ChatSession', 0)

    logger.info(
        'LangGraph 过期会话清理完成: retention_days=%s, cutoff_time=%s, removed_checkpoints=%s, '
        'deleted_sessions=%s, deleted_rows=%s, skipped_null_project=%s',
        retention_days,
        cutoff_time.isoformat(),
        removed_checkpoints,
        deleted_sessions,
        deleted_rows,
        skipped_null_project,
    )
    return {
        'status': 'success',
        'retention_days': retention_days,
        'cutoff_time': cutoff_time.isoformat(),
        'removed_checkpoints': removed_checkpoints,
        'deleted_sessions': deleted_sessions,
        'skipped_null_project': skipped_null_project,
    }


@shared_task(name='langgraph_integration.tasks.prune_checkpoint_history')
def prune_checkpoint_history():
    """按 thread 裁剪 checkpoint 历史，每个会话只保留最新（叶子）checkpoint。

    LangGraph 每轮对话都会在 checkpoints 表新增一行并复制整份状态快照
    （messages blob 存整份消息历史），多轮会话因此呈平方级膨胀。
    最新的 checkpoint 已包含用于恢复和展示的完整消息列表，旧快照可以安全删除。

    仅支持 postgres（psycopg2 风格，与 checkpointer.py 一致）。

    判断"最新"的方式：checkpoint_id 是 UUID，不保证单调，因此把
    没有被同 thread 其它 checkpoint 当作 parent 引用的 checkpoint（叶子/tip）
    视为最新保留。删除其它 checkpoint 后，一并清理：
    - checkpoint_writes 中 checkpoint_id 已不存在的行（按 thread_id + checkpoint_ns + checkpoint_id 关联）
    - checkpoint_blobs 中不再被任何保留 checkpoint 的 channel_versions 引用的行
      （blob 表没有 checkpoint_id，通过 thread_id + checkpoint_ns + channel + version 与
       checkpoints.checkpoint->'channel_versions' 关联）
    最后做一次全局孤儿清理，兜底已整线程删除后残留的 blobs/writes。
    """
    if get_database_type() != 'postgres':
        logger.info(
            'prune_checkpoint_history 跳过: 当前 DATABASE_TYPE=%s，仅支持 postgres',
            get_database_type(),
        )
        return {
            'status': 'skipped',
            'reason': 'not postgres',
            'threads_processed': 0,
            'checkpoints_removed': 0,
            'writes_removed': 0,
            'blobs_removed': 0,
            'orphan_writes_removed': 0,
            'orphan_blobs_removed': 0,
            'total_rows_removed': 0,
        }

    import psycopg2

    stats = {
        'threads_processed': 0,
        'checkpoints_removed': 0,
        'writes_removed': 0,
        'blobs_removed': 0,
        'orphan_writes_removed': 0,
        'orphan_blobs_removed': 0,
    }
    conn_string = get_db_connection_string()

    try:
        conn = psycopg2.connect(conn_string)
    except Exception as exc:
        logger.error('prune_checkpoint_history 连接数据库失败: %s', exc, exc_info=True)
        return {'status': 'error', 'error': str(exc), **stats}

    try:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT thread_id FROM checkpoints')
        thread_ids = [row[0] for row in cursor.fetchall()]
        conn.commit()

        for thread_id in thread_ids:
            stats['threads_processed'] += 1
            try:
                cursor = conn.cursor()

                # 1) 删除非叶子 checkpoint：被同 thread 其它 checkpoint 作为 parent 引用的行
                cursor.execute(
                    """
                    DELETE FROM checkpoints c
                    WHERE c.thread_id = %s
                      AND EXISTS (
                          SELECT 1 FROM checkpoints child
                          WHERE child.thread_id = c.thread_id
                            AND child.checkpoint_ns = c.checkpoint_ns
                            AND child.parent_checkpoint_id = c.checkpoint_id
                      )
                    """,
                    (thread_id,),
                )
                checkpoints_removed = cursor.rowcount

                # 2) 删除该 thread 内 checkpoint_id 已不存在的 checkpoint_writes
                cursor.execute(
                    """
                    DELETE FROM checkpoint_writes w
                    WHERE w.thread_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM checkpoints c
                          WHERE c.thread_id = w.thread_id
                            AND c.checkpoint_ns = w.checkpoint_ns
                            AND c.checkpoint_id = w.checkpoint_id
                      )
                    """,
                    (thread_id,),
                )
                writes_removed = cursor.rowcount

                # 3) 删除该 thread 内不再被保留 checkpoint 的 channel_versions 引用的 checkpoint_blobs
                cursor.execute(
                    """
                    DELETE FROM checkpoint_blobs b
                    WHERE b.thread_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM checkpoints c
                          WHERE c.thread_id = b.thread_id
                            AND c.checkpoint_ns = b.checkpoint_ns
                            AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version
                      )
                    """,
                    (thread_id,),
                )
                blobs_removed = cursor.rowcount

                conn.commit()
                stats['checkpoints_removed'] += checkpoints_removed
                stats['writes_removed'] += writes_removed
                stats['blobs_removed'] += blobs_removed
                if checkpoints_removed or writes_removed or blobs_removed:
                    logger.info(
                        'prune_checkpoint_history 裁剪完成: thread_id=%s, checkpoints_removed=%s, '
                        'writes_removed=%s, blobs_removed=%s',
                        thread_id,
                        checkpoints_removed,
                        writes_removed,
                        blobs_removed,
                    )
            except Exception as exc:
                conn.rollback()
                logger.error(
                    'prune_checkpoint_history 裁剪失败（已跳过该 thread）: thread_id=%s, error=%s',
                    thread_id,
                    exc,
                    exc_info=True,
                )

        # 4) 全局孤儿清理：兜底处理已整线程删除（旧版 cleanup 只删 checkpoints）后残留的数据
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM checkpoint_writes w
            WHERE NOT EXISTS (
                SELECT 1 FROM checkpoints c
                WHERE c.thread_id = w.thread_id
                  AND c.checkpoint_ns = w.checkpoint_ns
                  AND c.checkpoint_id = w.checkpoint_id
            )
            """
        )
        stats['orphan_writes_removed'] = cursor.rowcount

        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM checkpoint_blobs b
            WHERE NOT EXISTS (
                SELECT 1 FROM checkpoints c
                WHERE c.thread_id = b.thread_id
                  AND c.checkpoint_ns = b.checkpoint_ns
                  AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version
            )
            """
        )
        stats['orphan_blobs_removed'] = cursor.rowcount
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error('prune_checkpoint_history 执行失败: %s', exc, exc_info=True)
        return {'status': 'error', 'error': str(exc), **stats}
    finally:
        conn.close()

    stats['total_rows_removed'] = sum(
        stats[k] for k in ('checkpoints_removed', 'writes_removed', 'blobs_removed',
                           'orphan_writes_removed', 'orphan_blobs_removed')
    )
    stats['status'] = 'success'
    logger.info(
        'prune_checkpoint_history 完成: threads_processed=%s, checkpoints_removed=%s, '
        'writes_removed=%s, blobs_removed=%s, orphan_writes_removed=%s, orphan_blobs_removed=%s, '
        'total_rows_removed=%s',
        stats['threads_processed'],
        stats['checkpoints_removed'],
        stats['writes_removed'],
        stats['blobs_removed'],
        stats['orphan_writes_removed'],
        stats['orphan_blobs_removed'],
        stats['total_rows_removed'],
    )
    return stats

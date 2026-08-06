"""MySQL CRUD 测试（SQLite 内存库替代）。"""
import pytest
from backend.store import mysql_store
from backend.store import conversation_store


class TestKBCRUD:

    def test_create_and_get(self, db_session):
        """创建 KB → 可查询。"""
        kb_id = mysql_store.create_kb("测试库", "描述")
        assert kb_id > 0
        kb_list = mysql_store.list_kb()
        assert any(k["id"] == kb_id for k in kb_list)

    def test_delete_kb(self, db_session):
        """删除 KB → 列表中不存在。"""
        kb_id = mysql_store.create_kb("待删库")
        mysql_store.delete_kb(kb_id)
        kb_list = mysql_store.list_kb()
        assert not any(k["id"] == kb_id for k in kb_list)


class TestDocumentCRUD:

    def test_create_document(self, db_session, sample_kb):
        """插入文档 → 可列出。"""
        doc_id = mysql_store.create_document(sample_kb, "test.pdf")
        assert doc_id > 0
        docs = mysql_store.list_documents(sample_kb)
        assert any(d["id"] == doc_id for d in docs)

    def test_delete_document_cascades_chunks(self, db_session, sample_kb):
        """删除文档 → 级联清 chunk。"""
        doc_id = mysql_store.create_document(sample_kb, "cascade.pdf")
        mysql_store.insert_chunks(doc_id, sample_kb, [
            {"content": "chunk 1", "chunk_index": 0},
            {"content": "chunk 2", "chunk_index": 1},
        ])
        n = mysql_store.delete_document(doc_id)
        assert n == 2
        chunks = mysql_store.get_chunks(doc_id)
        assert chunks == []

    def test_delete_chunks_by_doc_id_only_chunks(self, db_session, sample_kb):
        """delete_chunks_by_doc_id 仅删 chunk，不删 document。"""
        doc_id = mysql_store.create_document(sample_kb, "partial.pdf")
        mysql_store.insert_chunks(doc_id, sample_kb, [
            {"content": "chunk A", "chunk_index": 0},
        ])
        n = mysql_store.delete_chunks_by_doc_id(doc_id)
        assert n == 1
        doc = mysql_store.get_document(doc_id)
        assert doc is not None
        assert mysql_store.get_chunks(doc_id) == []

    # ── P1-4: reset_stuck_documents 启动恢复 ──

    def test_reset_stuck_documents(self, db_session, sample_kb):
        """processing 文档被重置为 failed。"""
        # 创建文档并手动设为 processing
        doc_id = mysql_store.create_document(sample_kb, "stuck.pdf")
        mysql_store.update_document_status(doc_id, "processing")
        # 确认当前是 processing
        doc = mysql_store.get_document(doc_id)
        assert doc["status"] == "processing"
        # 执行恢复
        stuck = mysql_store.reset_stuck_documents()
        assert doc_id in stuck
        # 确认已重置为 failed
        doc = mysql_store.get_document(doc_id)
        assert doc["status"] == "failed"

    def test_reset_stuck_only_processing(self, db_session, sample_kb):
        """只重置 processing，不碰 done 和 pending。"""
        d1 = mysql_store.create_document(sample_kb, "done.pdf")
        d2 = mysql_store.create_document(sample_kb, "stuck.pdf")
        d3 = mysql_store.create_document(sample_kb, "pending.pdf")
        mysql_store.update_document_status(d1, "done")
        mysql_store.update_document_status(d2, "processing")
        # d3 has default status which is "pending"

        stuck = mysql_store.reset_stuck_documents()
        assert stuck == [d2]

        assert mysql_store.get_document(d1)["status"] == "done"
        assert mysql_store.get_document(d2)["status"] == "failed"
        # d3 is pending from create_document — but since we're not querying
        # it in reset_stuck_documents (which only looks for processing),
        # it should be unaffected.
        doc3 = mysql_store.get_document(d3)
        assert doc3["status"] != "failed"


class TestTags:

    def test_update_tags(self, db_session, sample_kb):
        """标签修改 → 可读取。"""
        doc_id = mysql_store.create_document(sample_kb, "tagged.pdf")
        tags = mysql_store.update_document_tags(doc_id, ["重要", "已审核"])
        assert "重要" in tags
        assert "已审核" in tags
        doc = mysql_store.get_document(doc_id)
        assert "重要" in doc["tags"]


# ── P1-3: conversation_store kb_ids 精确位置匹配 ──

class TestConversationKbIdFilter:

    def test_kb_id_exact_match(self, db_session):
        """kb_ids="1" 时按 kb_id=1 能精确匹配。"""
        cid = conversation_store.create_conversation(1, "1", "单库对话")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 1
        assert items[0]["id"] == cid

    def test_kb_id_first_position(self, db_session):
        """kb_ids="1,2,3" 时按 kb_id=1 精确匹配（开头位置）。"""
        cid = conversation_store.create_conversation(1, "1,2,3", "多库对话A")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 1
        assert items[0]["id"] == cid

    def test_kb_id_middle_position(self, db_session):
        """kb_ids="2,1,3" 时按 kb_id=1 精确匹配（中间位置）。"""
        cid = conversation_store.create_conversation(1, "2,1,3", "多库对话B")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 1
        assert items[0]["id"] == cid

    def test_kb_id_last_position(self, db_session):
        """kb_ids="2,3,1" 时按 kb_id=1 精确匹配（末尾位置）。"""
        cid = conversation_store.create_conversation(1, "2,3,1", "多库对话C")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 1
        assert items[0]["id"] == cid

    def test_kb_id_no_false_match(self, db_session):
        """kb_ids="11,12,21" 时按 kb_id=1 不应误匹配（旧 LIKE 会误伤）。"""
        conversation_store.create_conversation(1, "11,12", "不应出现")
        conversation_store.create_conversation(1, "21,31", "也不应出现")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 0

    def test_kb_id_mixed_with_target(self, db_session):
        """kb_ids="11,1,21" 混合时按 kb_id=1 能精确找出。"""
        cid = conversation_store.create_conversation(1, "11,1,21", "混合对话")
        items, total = conversation_store.list_conversations(1, kb_id=1)
        assert total == 1
        assert items[0]["id"] == cid

    def test_list_conversations_no_kb_filter(self, db_session):
        """不传 kb_id 时返回所有对话。"""
        c1 = conversation_store.create_conversation(1, "1,2", "对话A")
        c2 = conversation_store.create_conversation(1, "3", "对话B")
        items, total = conversation_store.list_conversations(1)
        assert total == 2

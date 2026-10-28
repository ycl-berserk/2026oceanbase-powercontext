# 数据库读写记录

seekdb 以 `pylibseekdb` 嵌入式运行，库文件默认 `data/seekdb/sdd.db`；PowerContext 的服务端数据库是独立的 SQLite，不在这里。

## 表结构

```sql
CREATE TABLE eng_docs (
  doc_key VARCHAR(191) PRIMARY KEY,
  kind VARCHAR(16) NOT NULL,            -- spec / code / test
  path VARCHAR(512) NOT NULL,
  symbol VARCHAR(191) NOT NULL,
  heading VARCHAR(255) NOT NULL,
  content TEXT NOT NULL,
  start_line INT NOT NULL,
  end_line INT NOT NULL,
  FULLTEXT INDEX ft_eng_content (content) WITH PARSER NGRAM
) ORGANIZATION = HEAP;
```

## 写入

`python -m sdd_context ingest --project workspace` 会按顺序执行：

```sql
DELETE FROM eng_docs;
REPLACE INTO eng_docs (doc_key, kind, path, symbol, heading, content, start_line, end_line)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
REPLACE INTO ingest_meta (meta_key, meta_value) VALUES ('ingested_at', %s);
```

一次导入的结果：

| kind | 条数 | 来源 |
| --- | ---: | --- |
| spec | 6 | `workspace/specs/tickets.md` 的 R1–R6 |
| code | 3 | `ticket_service` 的 `InvalidFilter`、`Ticket`、`list_tickets` |
| test | 10 | `workspace/tests/*.py` 的测试用例 |

## 检索

任务：`为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，结果按优先级和创建时间稳定排序`

```sql
SELECT doc_key, kind, path, symbol, heading, start_line, end_line,
       MATCH(content) AGAINST(%s) AS score
FROM eng_docs
WHERE kind = %s AND MATCH(content) AGAINST(%s)
ORDER BY score DESC, doc_key ASC
LIMIT 5;
```

实际命中（一次实测）：

| kind | doc_key | score |
| --- | --- | ---: |
| spec | `spec:tickets#R6` | 8.360691 |
| spec | `spec:tickets#R5` | 6.326565 |
| spec | `spec:tickets#R4` | 4.703236 |
| spec | `spec:tickets#R1` | 2.282718 |
| spec | `spec:tickets#R2` | 1.075947 |
| code | `code:ticket_service.errors:InvalidFilter` | 5.703786 |
| code | `code:ticket_service.service:list_tickets` | 5.340504 |
| code | `code:ticket_service.models:Ticket` | 3.062161 |
| test | `test:tests/test_priority_filter.py:test_rejects_unknown_priority` | 3.302200 |
| test | `test:tests/test_priority_filter.py:test_rejects_limit_out_of_range` | 3.267212 |
| test | `test:tests/test_priority_filter.py:test_filters_by_priority` | 3.056242 |
| test | `test:tests/test_priority_filter.py:test_orders_by_priority_then_recency` | 2.584655 |
| test | `test:tests/test_priority_filter.py:test_combines_status_and_priority` | 2.555824 |

同一份数据重复导入后，BM25 分数可能有小数点后的波动；召回集合与排序在本样例中保持稳定。

命中结果直接进入 `plan` 输出的 `specs` / `code` / `tests` 三段，`verify.py` 会逐条核对 `path:start_line-end_line` 是否存在。

## 复现

```bash
rm -rf data/seekdb
python -m sdd_context ingest --project workspace
python -m sdd_context plan --task "..." --task-id sdd-r4-r6 --json
```

# 基准测试与评测记录

## 协议（设计文档 §10.4）

每条结果必须记录：CPU / 内存 / GPU、模型与版本、文档数、切片数、并发数、
是否使用外部 API、git_sha、日期。缺任一元数据的结果不得引用。

## 消融矩阵（设计文档 §10.2）

```
A：纯稠密向量          B：BM25 + 稠密/稀疏
C：B + RRF             D：C + Reranker
E：D + GraphRAG 路由
```

指标：Recall@5/10、MRR、NDCG@5、Context Precision/Recall、答案正确率、
引用准确率、拒答准确率、阶段耗时。GraphRAG 对普通事实题与多跳题分开统计；
未提升的实验同样保留并分析。

## 运行方式

```bash
# 离线代理基线（BM25，无需模型服务）
.venv/bin/python -m eval.harness            # 或经 tests/test_eval_harness.py 自证

# 在线评测（需 docker compose up -d 与模型服务）
.venv/bin/python scripts/run_online_eval.py --strategy hybrid   # 待接入 v1 查询 API
```

## 当前状态

- 离线 harness 指标计算已单测自证（手算值 pin）。
- 在线检索质量、压测 P50/P95、建库吞吐：**未跑、未记录**——产出后以
  `benchmarks/YYYY-MM-DD-<campaign>.md` 归档并钉 git_sha。

# RAG 检索专题详解

> 检索（Retrieval）是 RAG 的"命门"：**检索质量决定了回答质量的上限**。如果检索回来的片段是错的，无论 LLM 多强，都只能基于错误资料"一本正经地胡说"。
>
> 本文以 PersonalKB-QA 项目为主线，把"检索"从原理到调优、从数学到工程完整讲透。建议先看完《知识点详解.md》再读本篇。

---

## 目录

1. [为什么检索是 RAG 的命门](#1-为什么检索是-rag-的命门)
2. [从关键词匹配到语义检索](#2-从关键词匹配到语义检索)
3. [本项目检索链路逐行拆解](#3-本项目检索链路逐行拆解)
4. [Embedding：把文字变成可计算的向量](#4-embedding把文字变成可计算的向量)
5. [余弦距离的坑（重点中的重点）](#5-余弦距离的坑重点中的重点)
6. [ChromaDB 与 HNSW 索引](#6-chromadb-与-hnsw-索引)
7. [影响检索质量的四大杠杆](#7-影响检索质量的四大杠杆)
8. [召回率、精确率与评估指标](#8-召回率精确率与评估指标)
9. [语义检索的三大短板与进阶方案](#9-语义检索的三大短板与进阶方案)
10. [动手实验清单](#10-动手实验清单)
11. [检索专题面试追问集](#11-检索专题面试追问集)

---

## 1. 为什么检索是 RAG 的命门

RAG 的完整链路是：

```
问题 → 检索 → [相关片段] → 拼进 Prompt → LLM 生成
```

这里有一个铁律：**LLM 只能基于你喂给它的资料回答**。所以：

- 检索**漏掉**了关键片段 → 模型"不知道"，只能兜底或编造（幻觉）；
- 检索**混入**了大量无关片段 → 上下文被噪声稀释，模型注意力分散，回答跑偏；
- 检索顺序**不合理**（最相关的排后面）→ 模型可能优先采用无关内容。

> 一句话总结：**检索是"输入质量"的守门员，生成是"输出质量"的加工者。垃圾进，垃圾出（Garbage In, Garbage Out）。**

这也是为什么很多 RAG 系统的优化，**80% 的精力花在检索侧**，而不是换更强的 LLM。

---

## 2. 从关键词匹配到语义检索

### 2.1 传统关键词检索（BM25 / TF-IDF）

最早的信息检索基于**词项匹配**：

- 把文档拆成词（分词），统计每个词出现的频率；
- 查询"苹果手机"时，去找**字面上包含这些词**的文档；
- **BM25** 是其中最经典、至今仍在工业界广泛使用的算法。

**优点**：精确词、专有名词、编号匹配极强；可解释、无需训练。

**缺点**：不懂**语义**。"iPhone 好不好用"和"苹果手机怎么样"字面没有一个词相同，BM25 匹配不到，但语义上是同一个问题。

### 2.2 语义检索（向量检索）

用 **Embedding 模型**把文本变成向量，靠向量相似度匹配：

- "iPhone 好不好用" → 向量 A
- "苹果手机怎么样" → 向量 B
- A 和 B 在向量空间里**很近**，于是能互相检索到。

**优点**：懂语义、能抗同义替换和口语化表达。

**缺点**：对**精确匹配**（合同编号、代码符号、人名精确拼写）不敏感；且"越强语义泛化，越容易忽略精确字符"。

### 2.3 本项目属于哪种

本项目是**纯向量语义检索**（ChromaDB + cosine）。DESIGN.md §14.2 已经预留了"混合检索（向量 + BM25）"作为后续增强——这正说明作者知道纯向量的短板。

> 面试话术：能说出"纯向量检索对精确术语/编号不敏感，理想方案是混合检索 + 重排"，是区分"背过概念"和"真正做过"的关键。

---

## 3. 本项目检索链路逐行拆解

完整检索流程（以问答为例）：

```
用户问题 question
   │
   ▼
① 问题向量化        embedding_service.embed_one(question)
   │                 └─ 得到 q_vec: list[float]（如 768 维）
   ▼
② 向量检索          retrieval_service.search(kb_id, q_vec, top_k)
   │                 └─ ChromaDB 返回 top_k 个最近邻 + 距离
   ▼
③ 相似度换算        similarity = 1 - distance   ← 关键！
   ▼
④ 阈值过滤          丢弃 similarity < 0.4 的片段
   ▼
⑤ 空检索兜底        若过滤后 0 条 → 不调 LLM，直接返回"暂无相关信息"
   ▼
⑥ 构建 Prompt       把片段编号拼进模板
   ▼
⑦ LLM 生成          llm_service.chat / chat_stream
```

### 3.1 代码定位

**① 问题向量化** —— `chat_service.py` 的 `_retrieve`：

```python
def _retrieve(kb_id: str, question: str) -> list[dict]:
    q_vec = embedding_service.embed_one(question)      # 问题 → 向量
    top_k = config.get("retrieval.top_k", 5)
    threshold = config.get("retrieval.similarity_threshold", 0.5)  # config.yaml 实际配 0.4
    results = retrieval_service.search(kb_id, q_vec, top_k)
    return [r for r in results if r["similarity"] >= threshold]   # ④ 阈值过滤
```

**② 向量检索 + ③ 相似度换算** —— `retrieval_service.py` 的 `search`：

```python
def search(kb_id, query_embedding, top_k):
    col = _collection(kb_id)
    res = col.query(query_embeddings=[query_embedding], n_results=top_k)
    # res 里有 ids / documents / metadatas / distances 四个列表
    ...
    for i in range(len(ids)):
        results.append({
            "id": ids[i],
            "content": documents[i],
            "document_name": metadatas[i]["document_name"],
            "similarity": round(1.0 - distances[i], 6),   # ③ 距离 → 相似度
        })
```

**⑤ 空检索兜底 + ⑥ 构建 Prompt** —— `chat_service.py`：

```python
if not chunks:
    answer = NO_INFO_ANSWER   # "知识库中暂无相关信息，无法回答该问题。"
else:
    answer = llm_service.chat(_build_prompt(question, chunks))
```

```python
def _build_prompt(question, chunks):
    chunk_text = "\n\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(chunks))
    return SYSTEM_PROMPT.format(chunks=chunk_text, question=question)
```

---

## 4. Embedding：把文字变成可计算的向量

### 4.1 向量是什么

向量就是一串数字，例如一个 3 维向量 `[0.1, 0.8, 0.3]` 可以画在三维坐标系里；768 维向量则是 768 维空间里的一个点。

Embedding 模型做的事：**把文本映射成高维空间里的一个点，语义相近的文本 → 空间里相近的点**。

### 4.2 余弦相似度：几何直觉 + 公式

两个向量 A、B 的余弦相似度是它们**夹角的余弦值**：

```
              A · B          Σ(ai × bi)
cos(A,B) = ─────────── = ─────────────────────
            |A| × |B|    √Σ(ai²) × √Σ(bi²)
```

- 夹角 0°（方向完全一致）→ cos = 1 → 最相似；
- 夹角 90°（正交）→ cos = 0 → 无关；
- 夹角 180°（完全相反）→ cos = -1。

**为什么用"夹角"而不是"距离"**：文本向量往往**长度受文本长度影响**，而余弦只关注**方向**（语义方向），对长度鲁棒。比如同一句话被复制三遍，向量长度变 3 倍，但方向不变，余弦相似度仍接近 1。

### 4.3 归一化后：余弦相似度 == 点积（本项目为什么 normalize）

如果先把向量**归一化**（让 |A| = |B| = 1），那么：

```
cos(A,B) = A · B = Σ(ai × bi)    （分母变成了 1×1）
```

**点积计算比"点积再除以两个模"更快**，所以很多向量库在 cosine 空间下要求/建议向量先归一化。

本项目 `embedding_service.py` 明确开了归一化：

```python
vecs = model.encode(texts, normalize_embeddings=normalize)  # normalize=True
```

这正好和 ChromaDB 的 `cosine` 度量**配套**（DESIGN.md 也强调"输出归一化向量，配合 cosine 度量"）。

> 面试追问：如果归一化了，`similarity` 直接等于点积，为什么代码里还要 `1 - distance`？—— 因为 ChromaDB 返回的 `distance` 是**余弦距离**（= 1 − 余弦相似度），这是 API 约定，和是否归一化无关。

### 4.4 中文 Embedding 模型 text2vec

本项目用 `shibing624/text2vec-base-chinese`：

- 基于中文预训练模型微调得到的**句向量**模型；
- 输出能反映句子级语义（而不是单词级）；
- 模型小、下载快、中文效果好。

选择 Embedding 模型的三个考量：**语言是否匹配**（中文任务用中文模型）、**维度与精度**（维度高更精确但更占内存/更慢）、**是否归一化**（影响度量选择）。

---

## 5. 余弦距离的坑（重点中的重点）

### 5.1 距离 vs 相似度：方向相反

- **相似度**：越大越像（范围 -1 ~ 1，余弦）；
- **距离**：越小越像（范围 0 ~ 2，余弦距离）。

两者关系：`余弦距离 = 1 − 余弦相似度`。

### 5.2 ChromaDB 的 API 约定

ChromaDB 的 `query` 返回的 `distances` 字段，**取决于建 Collection 时指定的 `hnsw:space`**：

| space | `distances` 含义 | 越小代表 |
|-------|-----------------|---------|
| `cosine` | 余弦距离（1 − cos） | 越相似 |
| `l2` | 欧氏距离 | 越相似 |
| `ip` | 内积（点积） | **越大**越相似（注意反了！） |

本项目建 Collection 时显式指定了 `cosine`：

```python
collection = client.get_or_create_collection(
    name=f"kb_{kb_id}",
    metadata={"hnsw:space": "cosine"},
)
```

所以 `distances` 是余弦距离，代码 `similarity = 1 - distance` 是**正确**的。

### 5.3 为什么阈值 0.5 在默认 L2 下是"灾难"

DESIGN.md v1.1 记录了 v1.0 的一个真实 bug：

- v1.0 没有显式指定 cosine，ChromaDB 默认用 **L2（欧氏距离）**；
- L2 距离的值**没有 0~1 的固定范围**，取决于向量维度和数值分布，可能是 0.3、也可能是 30；
- 于是 `similarity_threshold: 0.3`（本意是"相似度 > 0.3 才要"）在 L2 语义下**完全错误**，会把大量无关内容当成"相似"塞进 Prompt。

**教训**：度量空间（metric）和阈值（threshold）必须**配套**。换度量必须重新标定阈值。

### 5.4 三种度量怎么选（面试常问）

| 度量 | 公式 | 特点 | 适用 |
|------|------|------|------|
| 余弦 cosine | 看夹角 | 对向量长度鲁棒 | 文本语义（主流选择） |
| 欧氏 L2 | 看绝对距离 | 对长度/幅度敏感 | 图像特征、归一化后也可用 |
| 内积 dot/ip | 看投影 | 需归一化，否则受长度影响 | 部分模型（如部分 OpenAI embedding） |

**本项目选 cosine 的原因**：文本语义更适合用方向衡量，且配合 `normalize_embeddings=true`，归一化后 cosine 与点积等价、计算高效。

---

## 6. ChromaDB 与 HNSW 索引

### 6.1 为什么需要"向量索引"

朴素做法是**暴力全量比对**：拿问题向量和库里每一篇文档向量逐一算相似度，取 top_k。这在几十万、几百万向量时慢到不可用（O(N)）。

于是需要 **ANN（近似最近邻，Approximate Nearest Neighbor）**：牺牲一点点精度，换取数量级的速度提升。

### 6.2 HNSW 是什么（通俗理解）

HNSW = Hierarchical Navigable Small World（分层可导航小世界图）。

直觉理解：像**地铁线路图 + 高速路网**的组合——

- **上层**：稀疏的"高速路"，连接少数枢纽点，用于大范围快速跳跃；
- **下层**：密集的"小路"，连接附近点，用于局部精确定位。

查询时从最上层某个入口点开始，**逐层向下**：上层快速逼近目标区域，下层在附近精细搜索，最终找到最近邻。

- 优点：查询快、召回质量高；
- 代价：建索引和内存占用较大（`hnsw:space` 里的 `hnsw` 就是这套索引）。

**ChromaDB 的 `metadata={"hnsw:space": "cosine"}`** 就是在告诉它：建 HNSW 索引时，用 cosine 作为"远近"的度量。

### 6.3 PersistentClient 嵌入式模式

本项目用 `chromadb.PersistentClient(path=...)`：

- **嵌入式**：ChromaDB 作为一个库直接跑在 FastAPI 进程里，数据持久化到本地目录，无需单独起服务；
- 对比 `HttpClient`：连接独立部署的 Chroma 服务器（适合多实例共享、海量数据）。

个人知识库场景选嵌入式，简单、零运维。

### 6.4 Collection 与 Metadata 设计

- 每个知识库一个 Collection：`kb_{kb_id}`，隔离不同知识库的向量空间；
- 入库时每条向量带 metadata：`{"document_id": ..., "document_name": ...}`；
- **靠 metadata 做按文档删除**：`collection.delete(where={"document_id": doc_id})`（删除文档 / reprocess 前用）。

---

## 7. 影响检索质量的四大杠杆

检索质量不是单一参数决定的，而是**一条链路上每个环节共同作用**的结果。

### 7.1 杠杆一：分块策略（最容易被忽视，影响最大）

分块决定了"检索的最小单元"。块太大 → 噪声多、检索不精准；块太小 → 语义不完整、丢失上下文。

三个变量（本项目 `document_service.py` 的 `_split_text`）：

```python
RecursiveCharacterTextSplitter(
    chunk_size=500,      # 块大小
    chunk_overlap=50,    # 重叠
    separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
)
```

- **chunk_size**：500 字符是"经验值"，适合中等篇幅文档。要**按内容类型调**：规范文档/法律条文可能需更大，问答 FAQ 可能需更小。
- **chunk_overlap**：保留 50 字符重叠，防止把跨块边界的完整语义切断。
- **separators**：切分优先级。**中文标点（。！？；，）是中文切分的关键**，默认英文分隔符对中文切分质量差。

> 实验建议：对同一批文档，分别试 chunk_size = 200 / 500 / 800，人工看检索结果，找到"既完整又聚焦"的粒度。

### 7.2 杠杆二：Embedding 模型

- **语言匹配**：中文任务必须用中文友好的模型（如 text2vec），英文模型对中文语义理解差；
- **归一化**：配合 cosine 度量要 `normalize_embeddings=true`；
- **领域适配**：通用模型对垂直领域（医疗/法律/金融）可能不够，进阶做法是**领域微调**或用更强的模型。

### 7.3 杠杆三：top_k 与 threshold 的权衡

这是**召回率（Recall）与精确率（Precision）的博弈**：

| 调整 | 效果 | 代价 |
|------|------|------|
| 增大 top_k | 召回更多相关内容（不漏） | 可能混入无关内容，Prompt 变长 |
| 减小 top_k | Prompt 更干净 | 可能漏掉关键片段 |
| 降低 threshold | 召回更多（宽松） | 噪声多，甚至触发幻觉 |
| 提高 threshold | 更精准（严格） | 可能触发空检索兜底，答不上 |

**本项目的选择**：`top_k=5`、`threshold=0.4`。因为 text2vec 分数偏低，0.5 会误杀 0.4~0.5 的相关片段、频繁触发空检索兜底，所以从 0.5 调到 0.4——这是"先保召回，再靠 LLM/重排去噪"的取舍。

### 7.4 杠杆四：文档解析质量（上游的垃圾）

检索的输入是"解析出来的文本"。如果 PDF 提取出乱码、表格丢失、段落错乱，向量化出来的也是垃圾向量。

本项目解析（`document_service.py` 的 `_extract_text`）：
- txt/md 直接读文本（干净）；
- pdf 用 `PyPDFLoader`；
- docx 用 `Docx2txtLoader`。

> 局限：扫描版 PDF（图片型）用 PyPDF 提取不出文字，需要 OCR。这是常见的"检索不出来"根因之一。

---

## 8. 召回率、精确率与评估指标

**光靠"感觉检索还行"不靠谱**，要用指标量化。

### 8.1 基础概念

假设对某个问题，知识库里真正相关的文档是「黄金集合」（人工标注），检索返回了 K 个结果：

- **Recall@K（召回率）**：前 K 个结果里，命中了多少条"真正相关"的文档。
  - `Recall@K = 命中的相关文档数 / 相关文档总数`
  - 关心"**该找到的有没有找到**"。
- **Precision@K（精确率）**：前 K 个结果里，有多少条是真正相关的。
  - `Precision@K = 命中的相关文档数 / K`
  - 关心"**找到的是不是都是对的**"。

### 8.2 排序敏感指标

- **MRR（Mean Reciprocal Rank）**：看"第一个相关结果排在第几位"，取倒数后平均。越靠前 MRR 越高。
  - 第一个相关结果排第 1 → 1/1 = 1.0；排第 5 → 1/5 = 0.2。
- **nDCG**：不仅看"是否命中"，还看"排序质量"，相关性分等级加权。

### 8.3 怎么给本项目做检索评测

DESIGN.md §14.1 给了实操建议，落地步骤：

1. 准备 **10~20 条中文问题**，人工标注每条问题对应的"正确答案所在文档/chunk"；
2. 对每条问题跑 `retrieval_service.search`，取 top_k；
3. 计算 Recall@K、MRR；
4. 逐条**人工核对** Top-K 召回的 chunk 是否相关；
5. 根据结果调 `chunk_size` / `top_k` / `similarity_threshold`，再复测。

**项目已提供快捷工具**：`backend/verify_retrieval.py`（本次新增）封装了"embedding → 检索 → 打印相似度"这条链路，`python verify_retrieval.py <kb_id> <query>` 即可快速抽检，不用每次手写脚本。它不依赖 LLM key，所以能在接入 LLM 之前单独验证检索是否正常。

> 这一步非常值钱：**有评测数据，调参才有依据**；没有评测，调参就是"拍脑袋"。

---

## 9. 语义检索的三大短板与进阶方案

### 9.1 短板一：精确术语/编号匹配弱 → 混合检索（Hybrid Search）

**问题**：问"合同编号 ABC-2024-001 的违约条款是什么"，纯向量检索可能因为语义泛化而找不到这个**精确编号**。

**方案：混合检索 = 向量检索 + BM25 关键词检索**

- BM25 基于词项精确匹配，能精准命中"ABC-2024-001"；
- 向量检索补充语义；
- 两者结果用 **RRF（Reciprocal Rank Fusion，倒数排名融合）** 合并：

```
RRF_score(doc) = Σ 1 / (k + rank_i(doc))
```

其中 `rank_i` 是文档在第 i 路检索中的排名，k 是常数（通常 60）。简单说就是"在越多路里排名越靠前，总分越高"。

**如何接入本项目**：在 `retrieval_service` 增加一个 `hybrid_search`，BM25 可用 `rank_bm25` 库，对每个 chunk 建立 BM25 索引，两路检索后 RRF 融合。

### 9.2 短板二：排序不精 → 重排（Rerank）

**问题**：向量检索召回了 50 条"大致相关"，但**排序不准**——最相关的可能排在第 20 位。直接把 top_k 塞给 LLM 会浪费上下文、引入噪声。

**方案：两阶段检索（Retrieve → Rerank）**

1. **粗排（召回）**：向量检索快速召回 50~100 条候选；
2. **精排（重排）**：用一个专门的 **Rerank 模型**（如 bge-reranker、Cohere Rerank）对"问题 + 候选 chunk"逐对打分，重新排序；
3. 只取精排后的 top_k 给 LLM。

**为什么有效**：向量检索用"各自独立的向量"算相似度（双向都丢失了交互信息），而 Rerank 模型把"问题和文档**一起输入**"做交叉编码（cross-encoder），语义匹配更精细，只是更慢——所以只对少量候选做。

**如何接入本项目**：`chat_service._retrieve` 里，先 `search(top_k=50)` 召回，再调 Rerank 模型重排取前 5。

### 9.3 短板三：查询与文档表述差异大 → 查询改写 / HyDE / 多路召回

**问题**：用户问"这玩意儿怎么装"，文档里写的是"安装步骤"——口语化查询和书面化文档语义有距离，直接检索可能召回差。

三类方案：

1. **Query Rewriting（查询改写）**：用 LLM 先把问题改写/扩写成更适合检索的表述（如把"这玩意儿怎么装"改成"软件安装步骤教程"），再检索。
2. **HyDE（Hypothetical Document Embeddings）**：让 LLM 先"凭空写一段假设性答案"，再用这段答案去检索（因为假设答案的措辞更接近文档风格）。
3. **多路召回（Multi-query）**：用 LLM 把一个问题拆成多个不同角度的问题，分别检索后合并去重。

三者核心思想一致：**缩小"查询空间"与"文档空间"之间的语义鸿沟**。

---

## 10. 动手实验清单

> 理论看完，动手才能内化。以下是可操作的实验，按难度排序。

1. **观察距离**：临时写个脚本，把问题向量和几个"相关/无关"文本向量分别算 `similarity`，打印出来，直观感受余弦相似度的数值范围。
2. **改 top_k**：把 `config.yaml` 的 `retrieval.top_k` 从 5 改到 10，看 Prompt 里塞了多少无关内容。
3. **改 threshold**：把 `similarity_threshold` 改到 0.7，观察有多少问题会触发"暂无相关信息"兜底；改到 0.3，观察回答是否开始"跑偏"。
4. **改 chunk_size**：分别用 200/500/800 处理同一篇文档，问同样的问题，对比检索片段是否"完整且聚焦"。
5. **做一份评测集**：准备 10 条问题，人工标注正确答案，跑 `retrieval_service.search` 计算 Recall@K 和 MRR。
6. **（进阶）实现混合检索**：给 `retrieval_service` 加一个 `rank_bm25` 的 BM25 检索，与向量结果 RRF 融合，对比精确编号类问题的召回提升。

---

## 11. 检索专题面试追问集

### Q1. 余弦相似度和欧氏距离有什么区别？为什么文本检索常用余弦？
**答**：余弦衡量**方向**（夹角），对向量长度鲁棒；欧氏衡量**绝对距离**，对长度/幅度敏感。文本向量的模长常受文本长度影响，而"语义"主要体现在方向上，所以文本检索多用余弦。若向量已归一化，两者等价（余弦=点积，且与欧氏距离有确定关系）。

### Q2. 为什么这个项目里相似度要 `1 - distance`？
**答**：ChromaDB 在 `cosine` 空间下返回的 `distances` 是余弦距离（= 1 − 余弦相似度），所以转回相似度要 `1 - distance`。如果建 Collection 用了默认 L2，这个换算和 0.5 阈值就全错了。

### Q3. 为什么 embedding 要归一化？归一化后 cosine 和点积是什么关系？
**答**：归一化让向量模长为 1，此时余弦相似度等于点积（分母变成 1），计算更快；且配合向量库 cosine 度量更稳定。归一化后 cosine 与点积**等价**。

### Q4. 召回率（Recall）和精确率（Precision）怎么权衡？top_k 和 threshold 分别偏向哪个？
**答**：Recall 关心"该找的都找到没"，Precision 关心"找到的是不是都对"。增大 top_k、降低 threshold 偏向**提升 Recall**（但降 Precision）；减小 top_k、提高 threshold 偏向**提升 Precision**（但降 Recall）。RAG 里通常先保证 Recall（召回足够候选），再用 Rerank 提 Precision。

### Q5. 为什么 chunk 要 overlap？overlap 太大会怎样？
**答**：overlap 防止把跨块边界的完整语义切断，保证边界附近的上下文可被检索到。overlap 太大 → 冗余存储、重复召回、Prompt 里出现重复内容、向量库膨胀。

### Q6. HNSW 是什么？为什么向量库要它？
**答**：HNSW 是一种近似最近邻索引（分层可导航小世界图），用"分层图 + 逐层向下搜索"把查询复杂度从暴力全量比对的 O(N) 降到对数级，是"牺牲极小精度换数量级速度"的典型 ANN 方案。

### Q7. 纯向量检索有什么短板？怎么补？
**答**：短板是精确术语/编号/代码匹配弱、排序不精、口语化查询与书面文档有语义鸿沟。补齐手段：① 混合检索（向量 + BM25，RRF 融合）；② 两阶段重排（召回后用 Rerank 精排）；③ 查询改写 / HyDE / 多路召回。

### Q8. 如果检索老是答不上（触发空检索兜底），你会怎么排查？
**答**：系统性排查——① 阈值是否过高（适当调低）；② chunk 是否太小导致语义破碎（增大 chunk_size）；③ Embedding 模型是否匹配语言/是否归一化、与度量是否配套；④ 文档解析是否失败/乱码（尤其扫描版 PDF 需 OCR）；⑤ 知识库本身是否真的包含答案（RAG 不能无中生有）；⑥ 用评测集量化 Recall@K，而非凭感觉。

### Q9. 两阶段检索（Retrieve → Rerank）为什么比单阶段好？
**答**：单阶段向量检索用"两个独立向量"算相似度，丢失了查询与文档的细粒度交互；Rerank 用交叉编码把"问题+文档"一起输入，语义匹配更精细，排序更准。但 Rerank 慢，所以只对少量召回候选做——用"粗排保召回、精排保准确"分工。

### Q10. 用一句话总结本项目检索的完整数据流。
**答**：问题 → embed 成向量 → ChromaDB（cosine/HNSW）检索 top_k → 距离转相似度（1−distance）→ 阈值 0.4 过滤 → 空则兜底不调 LLM → 片段编号拼 Prompt → LLM 生成。

---

> 至此，RAG 检索从"是什么"到"怎么优化"已完整覆盖。下一步建议：照着《动手实验清单》改几个参数跑一遍，把上面的每个结论都亲手验证一次，理解会彻底不一样。

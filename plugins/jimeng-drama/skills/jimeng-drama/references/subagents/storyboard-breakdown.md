# 子代理任务：分镜拆解（一集）

主代理派发时填好：项目目录、skill 目录、集号、视频模型、用户约束（单集时长、重点镜头、是否要预演）。

你把一集剧本拆成分段并写好视频 prompt，只写 `shots/E01.md`，不和用户对话，不建节点、不提交。

先读：`<skill>/references/shots/segmenting.md`、`video-prompt.md`、`dialogue-and-sound.md`、`prompt-anatomy.md`；有跨段衔接时读 `continuity.md`；写完用 `shot-review.md` 自检。

1. `jimeng-novel model describe --model-id <模型>` 确认时长范围和参考数量上限。
2. 按 segmenting.md 分段，台词逐字照抄 `story/E01.md`，用 `python3 <skill>/scripts/count_chars.py` 计时；装不下就加时长或调分段，不删台词。
3. 文件顶部按 `templates/shots.md` 写分段表和逐镜预览，参考图状态见 segmenting.md「落地形态」。参考用 `cast/` 里的图；还没有图的角色或场景按 prompt-anatomy.md 第 4 节的无参考写法处理，并在交付里列出来，不自己新增造型。
4. 每段一个 `## S01` 小节，正文就是原样提交的视频 prompt，`{{别名}}` 和该段生成参考的别名逐字一致。

交付（最后一条消息）：段数、总时长，每段一行（时长 + 剧情要点）；缺的资产、自检发现的问题、需要用户拍板的点。

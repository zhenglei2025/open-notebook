'use client'

import Link from 'next/link'
import { ArrowLeft, BookOpenText } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Section = {
  id: string
  kicker: string
  title: string
}

type SectionHeaderProps = {
  kicker: string
  title: string
  intro?: string
}

const sections: Section[] = [
  { id: 'overview', kicker: 'OVERVIEW', title: '项目简介' },
  { id: 'workflow', kicker: 'WORKFLOW', title: '推荐工作流' },
  { id: 'features', kicker: 'FEATURES', title: '核心功能' },
  { id: 'research-tools', kicker: 'RESEARCH TOOLS', title: 'Research 功能' },
  { id: 'scenarios', kicker: 'SCENARIOS', title: '适用场景' },
  { id: 'faq', kicker: 'FAQ', title: '常见问题' },
  { id: 'roadmap', kicker: 'ROADMAP', title: '未来规划' },
]

const overviewCards = [
  {
    title: '数据可控',
    description: '支持自托管，资料和配置掌握在你自己手里，适合对隐私和可控性要求高的场景。',
  },
  {
    title: '模型可选',
    description: '支持内网的 GLM、Qwen 等多种模型调用，支持私有化部署。',
  },
  {
    title: '研究闭环',
    description: '从导入资料、提问、保存笔记到结构化提炼和播客生成，整个过程都在一个系统内完成。',
  },
]

const workflowSteps = [
  {
    title: '1. 创建 Notebook',
    description: '每个 Notebook 对应一个研究主题，比如“行业调研”“课程资料”“产品竞品分析”。不要把所有内容堆在同一个本子里。',
  },
  {
    title: '2. 添加 Source',
    description: '上传 PDF、网页链接、文本、音视频等资料。支持批量上传，等待系统完成解析和索引。',
  },
  {
    title: '3. 进入 Chat',
    description: '选择要带入上下文的资料后开始提问。第一轮建议先问“这份资料的核心结论是什么”。',
  },
  {
    title: '4. 需要成稿时用 Research',
    description: '如果你不只是想聊天，而是想直接产出一份研究报告，可以在聊天区切换到 Quick Research 或 Deep Research。规则复杂、格式严格的文档生成任务更适合 Deep Research。',
  },
  {
    title: '5. 需要落地文档时先保存为笔记',
    description: 'Research 结果先保存到笔记，再进行人工修改。笔记支持继续编辑，并导出为 Word、PDF、HTML 等格式。',
  },
  {
    title: '6. 需要汇报材料时生成 PPT',
    description: '当某条笔记已经整理成较完整内容后，可以在笔记编辑器里点击制作 PPT，让系统基于笔记自动生成演示文稿。',
  },
]

const featureCards = [
  {
    title: '添加资料',
    description: '支持 PDF、网页、文档、音频、视频、直接粘贴文本。系统会对内容进行处理，供后续聊天和搜索使用。',
  },
  {
    title: '上下文聊天',
    description: 'AI 回答不是凭空生成，而是基于你选中的资料上下文。适合问总结、比较、解释、提炼和延伸问题。',
  },
  {
    title: '笔记管理',
    description: '你可以手动写笔记，也可以把 AI 回答保存为笔记，用于沉淀结论、摘录、任务清单和整理结构。',
  },
  {
    title: '搜索',
    description: '既支持关键词精确检索，也支持语义相似检索。适合“找原句”和“找相关概念”两类不同需求。',
  },
  {
    title: 'Quick Research / Deep Research',
    description: '这两个模式会直接围绕你的问题生成研究报告，适合从“提问式探索”切换到“产出式研究”。',
  },
  {
    title: '基于笔记生成 PPT',
    description: '你可以把已经整理好的笔记转换成 PowerPoint，系统会异步生成任务，完成后可直接下载 `.pptx` 文件。',
  },
]

const researchModeCards = [
  {
    title: 'Quick Research',
    description: '入口在聊天面板。它会基于你的问题先规划报告结构，然后每个章节只做一轮搜索，跳过复杂评估，最后快速拼成一份报告，适合先拿到初稿。',
  },
  {
    title: 'Deep Research',
    description: '同样从聊天面板触发，但流程更完整。它会先做大纲规划，再按章节搜索、评估材料是否足够、必要时扩展到全文阅读，最后编译成更完整、更有层次的研究报告。',
  },
  {
    title: '生成 PPT',
    description: '入口在笔记编辑器。系统会把笔记内容交给模型生成幻灯片结构，再套用项目里的 PPT 模板生成可下载文件，适合把研究结果转成汇报材料。',
  },
]

const researchTable = [
  ['Quick Research', '想快速拿到结构化报告初稿', '速度更快，搜索轮次更少，直接生成结果，适合快速调研'],
  ['Deep Research', '想要更完整、更稳的研究报告', '会按章节做搜索与评估，必要时读全文，生成过程更深、更慢，但通常更扎实'],
  ['生成 PPT', '已经有笔记或报告，准备做展示', '基于笔记内容生成幻灯片任务，可追加“控制在 10 页内”“突出关键发现”等要求'],
]

const researchExplainCards = [
  {
    title: 'Quick Research 在做什么',
    description: '从代码实现看，它会先为问题规划章节，再对每个章节执行一次搜索并直接写出内容，省略了材料充分性评估和更复杂的章节精修，所以更适合速度优先的场景。',
    tone: 'blue',
  },
  {
    title: 'Deep Research 在做什么',
    description: '它会先围绕问题做检索和大纲规划，再对每个章节循环执行“搜索 → 评估是否足够 → 必要时扩展上下文 → 写作 → 汇总”，因此更像一个多阶段研究代理。',
    tone: 'amber',
  },
]

const researchUsageCards = [
  {
    title: '如何使用 Quick / Deep Research',
    description: '在 Notebook 的聊天区，先确保上下文已开启并选好资料，再点击工具栏里的 Quick Research 或 Deep Research，输入问题后系统会在后台跑任务，并在界面中展示进度和最终报告。',
  },
  {
    title: '如何使用 PPT 生成功能',
    description: '先打开一条已有笔记，点击“制作 PPT”，可选填写附加要求，例如“突出结论、控制在 10 页以内”。任务完成后会出现在 PPT 任务列表里，并支持下载。',
  },
]

const patentSteps = [
  {
    title: '1. 创建专门的 Notebook',
    description: '例如命名为“多模态 RAG 强化学习专利提案”。这个 Notebook 用来承载本次专利草案相关资料和输出。',
  },
  {
    title: '2. 批量上传规则资料',
    description: '上传专利提案表模板、专利评审标准、中国银联专利工作管理办法等规则性文件。这类资料通常是长期复用的基础规则。',
  },
  {
    title: '3. 上传本次研发材料',
    description: '继续上传本次专利相关研发文档，以及一份 skill.md，把用户的个性化要求、写作目标和重点创新点写进去。',
  },
  {
    title: '4. 在 Chat 中直接按 skill 发起问题',
    description: '用户的 query 可以非常简单，例如“请根据我上传的 skill 模板，帮我生成报告”。模型重点参考 skill.md 和上下文中的规则文件来写提案表。',
  },
  {
    title: '5. 选择 Deep Research 开始生成',
    description: '由于这类任务既要遵守模板，又要整合创新点并匹配评审标准，Deep Research 比普通聊天或 Quick Research 更合适。',
  },
  {
    title: '6. 结果保存到笔记并人工修订',
    description: 'Deep Research 生成提案表后，先保存到笔记。笔记支持继续手动修改，便于法律部或发明人补充措辞、调整表述和校正细节。',
  },
  {
    title: '7. 导出 Word、PDF 等格式',
    description: '笔记编辑器里已经支持导出 Word、PDF、HTML，本地整理和提交会更方便。后续如果还要汇报，也可以继续基于笔记生成 PPT。',
  },
  {
    title: '8. 新创新点可复用规则资料',
    description: '当后续要针对新的创新点再生成提案表时，规则文件通常不需要重复上传，可以继续复用；只需要补充新的研发文档，开启新会话重新执行 Deep Research 即可。',
  },
]

const skillCards = [
  {
    title: 'skill.md 在这个场景里的作用',
    description: 'skill.md 相当于一份“任务意图说明书”。它可以把发明主题、必须遵循的模板、创新点来源、写作风格和生成目标写清楚，让模型更稳定地输出符合要求的专利提案表。',
  },
  {
    title: 'skill.md 可定制、可共享',
    description: '用户可以按项目需求随时调整 skill.md 内容。未来如果系统支持共享型 skill，这类专利提案模板也很适合沉淀成可复用的团队能力。',
  },
]

const skillExample = `skill.md 示例思路

我需要写 1 份基于强化学习的多模态检索增强生成方法的专利。
context 中已经上传了专利提案表（2025 版）模板、专利评审标准（2025 版）、
中国银联专利工作管理办法等要求，请根据这些标准和规则，
基于 “R3-RAG-Learning Step-by-Step Reasoning and Retrieval for LLMs via Reinforcement Learning”
和“创新点思考”两份文件提供的主要创新点，
帮我按照专利提案表（2025 版）模板要求生成一份专利提案表。`

const scenarioCards = [
  {
    title: '论文和课程资料整理',
    description: '把 PDF、讲义和网页资料放在一个 Notebook 中，围绕概念、方法和对比持续追问。',
  },
  {
    title: '行业与竞品调研',
    description: '导入报告、官网、访谈稿和产品说明，快速抽取重点、归纳差异并沉淀为笔记。',
  },
  {
    title: '个人知识库',
    description: '适合把零散资料集中起来，让 AI 帮你总结、联想和复盘，而不是单纯堆文件。',
  },
  {
    title: '法律与专利材料生成',
    description: '适合把模板、制度办法、评审标准和研发资料一起放进 Notebook，用 Deep Research 生成专利提案表、制度化初稿或合规说明文档。',
  },
]

const faqCards = [
  {
    title: '页面能打开，但不能问答',
    description: '通常是还没配置 API Key，或者模型还没注册成功。先去设置里测试连接和发现模型。',
  },
  {
    title: '搜索结果不理想',
    description: '如果你记得关键词，用文本搜索；如果只记得大意或主题，用向量搜索。两种方式要分开使用。',
  },
  {
    title: '一个 Notebook 放太多东西会怎样',
    description: '上下文会变杂，结果更难聚焦。推荐按研究主题拆分，不同项目分别建立 Notebook。',
  },
  {
    title: '本地模型能不能用',
    description: '可以。项目支持 Ollama、LM Studio 等本地方案，适合更注重隐私或想控制成本的场景。',
  },
  {
    title: 'Quick Research 和 Deep Research 怎么选',
    description: '先用 Quick Research 拿初稿、看方向；当你要更完整、更有条理、对材料覆盖更充分的结果时，再用 Deep Research。',
  },
  {
    title: 'PPT 是直接拿原始文件生成吗',
    description: '不是，它是基于“笔记内容”生成的。所以更推荐先把结论整理成一条比较完整的笔记，再去制作 PPT，效果会更稳定。',
  },
  {
    title: '规则文件每次都要重新上传吗',
    description: '不一定。如果是长期稳定的模板、管理办法、评审标准，可以在同一个 Notebook 中长期复用；后续换新的创新点时，只补新的研发文档并新建会话即可。',
  },
  {
    title: 'skill.md 一定要固定吗',
    description: '不是。它本质上是用户可自定义的任务说明文件，可以按专利类型、部门习惯或文档要求持续调整。后续也很适合演进成共享型 skill。',
  },
]

const roadmapCards = [
  {
    title: 'Deep Research 支持定制 Skill',
    description: '后续会让 Deep Research 更好地支持用户自定义 Skill，把专利提案、行业分析、制度解读、汇报写作等固定流程沉淀成可复用能力。',
  },
  {
    title: 'PPT 生成功能持续迭代',
    description: '会继续增强基于笔记生成 PPT 的能力，包括更稳定的结构生成、更好的版式控制，以及更贴近业务汇报场景的输出效果。',
  },
  {
    title: '引入更多 PPT 生成能力',
    description: '未来会考虑购买或引入其他成熟的 PPT 生成能力，让演示文稿输出不只停留在基础排版，而是具备更强的设计感和业务表达能力。',
  },
  {
    title: '播客生成接入内部 ASR / TTS',
    description: '后续计划更多使用内部 ASR 和 TTS 能力，生成更自然的对话型播客，方便把研究内容转换成可听化材料。',
  },
  {
    title: '联网搜索能力',
    description: '等后续内网和外网链路打通后，系统可以在互联网搜索资料，让 Notebook 不只依赖本地上传内容，也能结合外部公开信息做研究。',
  },
  {
    title: '企业内网资料整合',
    description: '随着内网能力逐步完善，后续也会更适合接入企业已有知识库、制度文档和项目资料，让研究流程真正融入内部工作环境。',
  },
]

function SectionHeader({ kicker, title, intro }: SectionHeaderProps) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary/80">{kicker}</div>
      <h2 className="text-3xl font-bold tracking-tight text-foreground">{title}</h2>
      {intro ? <p className="max-w-3xl text-sm leading-7 text-muted-foreground">{intro}</p> : null}
    </div>
  )
}

function InfoCard({ title, description }: { title: string; description: string }) {
  return (
    <Card className="gap-0 border-border/70 shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm leading-8 text-muted-foreground">
        {description}
      </CardContent>
    </Card>
  )
}

export default function GuidePage() {
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-muted/20">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6">
          <Card className="overflow-hidden border-primary/10 bg-gradient-to-r from-primary/10 via-background to-primary/5 py-0 shadow-sm">
            <CardContent className="p-6 md:p-8">
              <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-4">
                    <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-background/80 px-3 py-1 text-xs font-medium text-primary shadow-sm">
                      <BookOpenText className="h-3.5 w-3.5" />
                      使用指南
                    </div>
                    <div className="space-y-3">
                      <h1 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                        UP Notebook 使用指南
                      </h1>
                      <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
                        这是一份面向普通使用者的应用内说明页，重点放在日常使用流程、Research 产出、
                        文档导出和后续规划。页面内容保持现有说明不变，但交互和视觉更贴近当前 Notebook 界面。
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 md:items-end">
                    <Button asChild variant="outline" className="w-fit bg-background/90">
                      <Link href="/feedback">
                        <BookOpenText className="mr-2 h-4 w-4" />
                        去提交使用反馈
                      </Link>
                    </Button>
                    <Button asChild variant="outline" className="w-fit bg-background/90">
                      <Link href="/notebooks">
                        <ArrowLeft className="mr-2 h-4 w-4" />
                        返回笔记本
                      </Link>
                    </Button>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
                  <div className="rounded-2xl border border-border/70 bg-background/80 p-4 shadow-sm">
                    <div className="mb-2 text-sm font-semibold text-foreground">模型能力</div>
                    <p className="text-sm leading-7 text-muted-foreground">支持内网 GLM、Qwen 等多种模型调用，支持私有化部署。</p>
                  </div>
                  <div className="rounded-2xl border border-border/70 bg-background/80 p-4 shadow-sm">
                    <div className="mb-2 text-sm font-semibold text-foreground">资料范围</div>
                    <p className="text-sm leading-7 text-muted-foreground">支持 PDF、网页、音频、视频、纯文本等多模态资料。</p>
                  </div>
                  <div className="rounded-2xl border border-border/70 bg-background/80 p-4 shadow-sm">
                    <div className="mb-2 text-sm font-semibold text-foreground">研究产出</div>
                    <p className="text-sm leading-7 text-muted-foreground">可以对资料聊天、搜索、做引用校验、生成摘要和结构化输出。</p>
                  </div>
                  <div className="rounded-2xl border border-border/70 bg-background/80 p-4 shadow-sm">
                    <div className="mb-2 text-sm font-semibold text-foreground">文档能力</div>
                    <p className="text-sm leading-7 text-muted-foreground">支持 Quick Research、Deep Research 和基于笔记生成 PPT。</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid items-start gap-6 xl:grid-cols-[260px_minmax(0,1fr)]">
            <Card className="top-6 gap-0 xl:sticky">
              <CardHeader className="pb-3">
                <CardTitle className="text-2xl">目录</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-7 text-muted-foreground">
                  这是一个应用内单页说明，重点放在日常使用流程、研究产出和文档导出。
                </p>
                <div className="space-y-2">
                  {sections.map((section, index) => (
                    <a
                      key={section.id}
                      href={`#${section.id}`}
                      className="flex items-center rounded-xl border border-transparent bg-muted/50 px-4 py-3 text-sm font-medium text-foreground transition-colors hover:border-border hover:bg-accent"
                    >
                      {index + 1}. {section.title}
                    </a>
                  ))}
                </div>
                <div className="rounded-2xl border border-primary/10 bg-primary/5 p-4 text-sm leading-7 text-muted-foreground">
                  普通用户主线：创建 Notebook → 添加资料 → 开始 Chat → 需要成稿时切到 Quick Research 或
                  Deep Research → 保存为笔记并导出 → 需要汇报时生成 PPT。
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card id="overview" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader
                    kicker="OVERVIEW"
                    title="项目简介"
                    intro="UP Notebook 可以理解为一个“带 AI 的研究资料工作台”。它和普通聊天工具的区别在于：资料是你主动导入和组织的，AI 回答建立在这些资料之上，而且可以结合搜索、笔记、转换模板和播客生成功能形成完整工作流。"
                  />
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-3">
                  {overviewCards.map((card) => (
                    <InfoCard key={card.title} {...card} />
                  ))}
                </CardContent>
              </Card>

              <Card id="workflow" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader
                    kicker="WORKFLOW"
                    title="推荐工作流"
                    intro="如果你是第一次用 UP Notebook，建议按下面这条路径走。这样最容易把“资料、上下文、问答、笔记”这几件事串起来。"
                  />
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  {workflowSteps.map((step) => (
                    <InfoCard key={step.title} {...step} />
                  ))}
                </CardContent>
              </Card>

              <Card id="features" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader kicker="FEATURES" title="核心功能" />
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  {featureCards.map((card) => (
                    <InfoCard key={card.title} {...card} />
                  ))}
                </CardContent>
              </Card>

              <Card id="research-tools" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader
                    kicker="RESEARCH TOOLS"
                    title="Quick Research、Deep Research 与 PPT"
                    intro="这是 UP Notebook 里比较“产出导向”的三项能力。它们都不只是简单回答一句话，而是把你已有的资料进一步加工成更完整的结果。"
                  />
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-3">
                    {researchModeCards.map((card) => (
                      <InfoCard key={card.title} {...card} />
                    ))}
                  </div>

                  <div className="overflow-hidden rounded-2xl border border-border/70">
                    <table className="w-full border-collapse text-left text-sm">
                      <thead className="bg-muted/50">
                        <tr>
                          <th className="px-4 py-3 font-semibold text-foreground">功能</th>
                          <th className="px-4 py-3 font-semibold text-foreground">更适合什么情况</th>
                          <th className="px-4 py-3 font-semibold text-foreground">特点</th>
                        </tr>
                      </thead>
                      <tbody>
                        {researchTable.map((row) => (
                          <tr key={row[0]} className="border-t border-border/70 bg-background">
                            {row.map((cell) => (
                              <td key={cell} className="px-4 py-4 align-top leading-7 text-muted-foreground">
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    {researchExplainCards.map((card) => (
                      <div
                        key={card.title}
                        className={`rounded-2xl border p-5 shadow-sm ${
                          card.tone === 'amber'
                            ? 'border-amber-200 bg-amber-50/70 dark:border-amber-500/20 dark:bg-amber-500/5'
                            : 'border-primary/15 bg-primary/5'
                        }`}
                      >
                        <div className="mb-2 text-base font-semibold text-foreground">{card.title}</div>
                        <p className="text-sm leading-7 text-muted-foreground">{card.description}</p>
                      </div>
                    ))}
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    {researchUsageCards.map((card) => (
                      <InfoCard key={card.title} {...card} />
                    ))}
                  </div>

                  <div className="rounded-2xl border border-primary/15 bg-primary/5 p-5 shadow-sm">
                    <div className="mb-2 text-base font-semibold text-foreground">Deep Research 用法示例：法律部生成专利提案表</div>
                    <p className="text-sm leading-7 text-muted-foreground">
                      这是一个很适合 Deep Research 的真实范式。场景是法律部或知识产权同事，需要基于固定模板、
                      评审标准、管理办法和本次研发创新点，自动生成一份专利提案表初稿。
                    </p>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    {patentSteps.map((step) => (
                      <InfoCard key={step.title} {...step} />
                    ))}
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    {skillCards.map((card) => (
                      <InfoCard key={card.title} {...card} />
                    ))}
                  </div>

                  <div className="overflow-hidden rounded-2xl border border-border/70 bg-slate-950 text-slate-50 shadow-sm">
                    <pre className="overflow-x-auto px-5 py-4 text-sm leading-7">{skillExample}</pre>
                  </div>
                </CardContent>
              </Card>

              <Card id="scenarios" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader kicker="SCENARIOS" title="适用场景" />
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  {scenarioCards.map((card) => (
                    <InfoCard key={card.title} {...card} />
                  ))}
                </CardContent>
              </Card>

              <Card id="faq" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader kicker="FAQ" title="常见问题" />
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-2">
                    {faqCards.map((card) => (
                      <InfoCard key={card.title} {...card} />
                    ))}
                  </div>
                  <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-5 shadow-sm dark:border-amber-500/20 dark:bg-amber-500/5">
                    <div className="mb-2 text-base font-semibold text-foreground">最常见的误区</div>
                    <p className="text-sm leading-7 text-muted-foreground">
                      把它当成“普通聊天网页”来用。UP Notebook 的价值不只是聊天，而是把资料组织、引用、搜索、研究成稿、汇报输出和知识沉淀串成一个流程。
                    </p>
                  </div>
                </CardContent>
              </Card>

              <Card id="roadmap" className="scroll-mt-6 gap-0">
                <CardHeader>
                  <SectionHeader
                    kicker="ROADMAP"
                    title="未来规划"
                    intro="UP Notebook 后续会继续围绕“研究效率、内容产出、企业内网能力整合”这三条主线迭代，下面是当前比较明确的方向。"
                  />
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  {roadmapCards.map((card) => (
                    <InfoCard key={card.title} {...card} />
                  ))}
                </CardContent>
              </Card>

              <Card className="border-primary/10 bg-gradient-to-r from-primary/10 via-background to-primary/5 py-0 shadow-sm">
                <CardContent className="p-6 text-sm leading-7 text-muted-foreground">
                  建议把这个页面当成快速入门版说明。真正上手时，最关键的不是把所有功能都看一遍，
                  而是先完成一次完整闭环：创建 Notebook、导入资料、提出问题、保存笔记。跑通一次之后，
                  你会更容易理解 UP Notebook 的使用方式。
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}

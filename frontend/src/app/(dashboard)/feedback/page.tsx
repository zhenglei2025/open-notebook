'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ArrowLeft, Bug, Lightbulb, Loader2, MessageSquareWarning } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/lib/hooks/use-toast'
import { useAuthStore } from '@/lib/stores/auth-store'
import { feedbackApi, FeedbackCategory } from '@/lib/api/feedback'

const feedbackOptions: Array<{
  value: FeedbackCategory
  label: string
  description: string
  icon: typeof Lightbulb
}> = [
  {
    value: 'feature',
    label: '需求建议',
    description: '填写你希望新增的功能、流程优化或体验改进。',
    icon: Lightbulb,
  },
  {
    value: 'bug',
    label: 'Bug 反馈',
    description: '描述你遇到的问题、报错信息、复现步骤或异常现象。',
    icon: Bug,
  },
]

export default function FeedbackPage() {
  const { toast } = useToast()
  const { username } = useAuthStore()

  const [category, setCategory] = useState<FeedbackCategory>('feature')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const selectedOption = feedbackOptions.find(option => option.value === category) ?? feedbackOptions[0]
  const SelectedIcon = selectedOption.icon

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const trimmedTitle = title.trim()
    const trimmedDescription = description.trim()
    if (trimmedTitle.length < 3) {
      toast({
        title: '标题太短',
        description: '请至少填写 3 个字，让管理员更容易判断你的反馈内容。',
        variant: 'destructive',
      })
      return
    }
    if (trimmedDescription.length < 10) {
      toast({
        title: '描述不够详细',
        description: '请至少填写 10 个字，尽量把背景、问题或诉求说明白。',
        variant: 'destructive',
      })
      return
    }

    setSubmitting(true)
    try {
      await feedbackApi.create({
        category,
        title: trimmedTitle,
        description: trimmedDescription,
      })
      toast({
        title: '反馈已提交',
        description: '管理员已经可以在后台看到这条反馈了，感谢你的建议。',
      })
      setTitle('')
      setDescription('')
      setCategory('feature')
    } catch (error) {
      console.error('Failed to submit feedback:', error)
      toast({
        title: '提交失败',
        description: '这次反馈没有成功提交，请稍后再试。',
        variant: 'destructive',
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-muted/20">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 md:p-6">
          <Card className="overflow-hidden border-primary/10 bg-gradient-to-r from-primary/10 via-background to-primary/5 py-0 shadow-sm">
            <CardContent className="p-6 md:p-8">
              <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
                <div className="space-y-4">
                  <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-background/80 px-3 py-1 text-xs font-medium text-primary shadow-sm">
                    <MessageSquareWarning className="h-3.5 w-3.5" />
                    使用反馈
                  </div>
                  <div className="space-y-3">
                    <h1 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                      告诉我们你想要什么，或者哪里出了问题
                    </h1>
                    <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
                      你可以在这里提交功能需求、体验建议或 bug 描述。提交后，管理员会在“用户管理”页面看到你的反馈内容。
                    </p>
                  </div>
                </div>

                <div className="flex flex-col items-start gap-2">
                  <Button asChild variant="outline" className="w-fit bg-background/90">
                    <Link href="/guide">
                      <ArrowLeft className="mr-2 h-4 w-4" />
                      返回使用指南
                    </Link>
                  </Button>
                  <div className="text-sm text-muted-foreground">
                    当前提交用户：<span className="font-medium text-foreground">{username ?? '未登录用户'}</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle className="text-2xl">提交反馈</CardTitle>
              </CardHeader>
              <CardContent>
                <form className="space-y-5" onSubmit={handleSubmit}>
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">反馈类型</label>
                    <Select value={category} onValueChange={(value) => setCategory(value as FeedbackCategory)}>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="请选择反馈类型" />
                      </SelectTrigger>
                      <SelectContent>
                        {feedbackOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <div className="flex items-start gap-2 rounded-xl border border-border/70 bg-muted/40 p-3 text-sm text-muted-foreground">
                      <SelectedIcon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <span>{selectedOption.description}</span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="feedback-title" className="text-sm font-medium text-foreground">
                      标题
                    </label>
                    <Input
                      id="feedback-title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder="例如：希望增加批量删除来源 / 上传 zip 后某类文件解析失败"
                      maxLength={120}
                    />
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="feedback-description" className="text-sm font-medium text-foreground">
                      详细描述
                    </label>
                    <Textarea
                      id="feedback-description"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="请尽量写清楚你的需求背景，或者 bug 的复现步骤、报错信息、期望结果。"
                      className="min-h-40"
                      maxLength={4000}
                    />
                    <div className="text-right text-xs text-muted-foreground">
                      {description.length} / 4000
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setCategory('feature')
                        setTitle('')
                        setDescription('')
                      }}
                      disabled={submitting}
                    >
                      清空
                    </Button>
                    <Button type="submit" disabled={submitting}>
                      {submitting ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          提交中
                        </>
                      ) : (
                        '提交反馈'
                      )}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle className="text-lg">填写建议</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm leading-7 text-muted-foreground">
                  <p>如果是功能需求，建议写清楚你现在的工作流、卡点，以及你希望系统怎么帮你。</p>
                  <p>如果是 bug，建议写清楚操作步骤、报错提示，以及是否能稳定复现。</p>
                  <p>如果方便，也可以附带文件类型、页面路径、按钮名称等上下文，管理员排查会更快。</p>
                </CardContent>
              </Card>

              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle className="text-lg">管理员会看到什么</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm leading-7 text-muted-foreground">
                  <p>提交用户</p>
                  <p>反馈类型</p>
                  <p>标题与完整描述</p>
                  <p>提交时间</p>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}

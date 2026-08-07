import { useState, useEffect } from 'react'
import {
  ArrowLeft,
  MessageSquare,
  BookOpen,
  Send,
  Loader2,
  Sparkles,
  FileText,
  Clock,
  ChevronRight,
  Search,
  Home,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'

const API_BASE = import.meta.env.VITE_API_BASE || ''

interface BloggerDetail {
  id: number
  nickname: string
  signature: string
  follower_count: number
  total_videos: number
  processed_videos: number
  master_summary: string | null
  master_topics: string[] | null
  master_keywords: string[] | null
}

interface Video {
  id: number
  aweme_id: string
  title: string
  desc: string
  duration: number
  digg_count: number
  comment_count: number
  create_time: string | null
  summary: string | null
  key_points: string[] | null
  topics: string[] | null
  takeaways: string | null
  transcript: string | null
  status: string
}

interface KnowledgeDocProps {
  bloggerId: number
  onBack: () => void
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  return text
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\* (.+)$/gm, '<li>$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
}

function formatNumber(num: number): string {
  if (!num) return '0'
  if (num >= 10000) return (num / 10000).toFixed(1) + 'w'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'k'
  return num.toString()
}

function formatDuration(sec: number): string {
  if (!sec) return '0:00'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return `${d.getFullYear()}-${(d.getMonth()+1).toString().padStart(2,'0')}-${d.getDate().toString().padStart(2,'0')}`
  } catch {
    return dateStr
  }
}

export default function KnowledgeDoc({ bloggerId, onBack }: KnowledgeDocProps) {
  const [blogger, setBlogger] = useState<BloggerDetail | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [activeView, setActiveView] = useState<'master' | 'video'>('master')
  const [activeVideoId, setActiveVideoId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState<any[]>([])
  const [tab, setTab] = useState<'doc' | 'qa'>('doc')
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    loadData()
  }, [bloggerId])

  async function loadData() {
    setLoading(true)
    try {
      const [bloggerRes, videosRes] = await Promise.all([
        fetch(`${API_BASE}/api/bloggers/${bloggerId}`),
        fetch(`${API_BASE}/api/bloggers/${bloggerId}/videos`)
      ])
      const bloggerData = await bloggerRes.json()
      const videosData = await videosRes.json()
      setBlogger(bloggerData)
      setVideos(Array.isArray(videosData) ? videosData : [])
      if (bloggerData.master_summary) {
        setActiveView('master')
      } else if (videosData.length > 0) {
        setActiveView('video')
        setActiveVideoId(videosData[0].id)
      }
    } catch (e) {
      console.error('加载数据失败', e)
    } finally {
      setLoading(false)
    }
  }

  const filteredVideos = videos.filter(v => 
    !searchQuery || v.title?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const activeVideo = videos.find(v => v.id === activeVideoId)

  const handleAsk = async () => {
    if (!question.trim()) return
    setAsking(true)
    setAnswer('')
    setSources([])
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blogger_id: bloggerId, query: question, top_k: 5 })
      })
      const data = await res.json()
      setAnswer(data.answer || '抱歉，暂时无法回答这个问题。')
      setSources(data.sources || [])
    } catch (e) {
      setAnswer('网络错误，请稍后重试。')
    } finally {
      setAsking(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center bg-[#FAFAFA]">
        <div className="flex items-center gap-2 text-[#666]">
          <Loader2 size={20} className="animate-spin" />
          <span className="text-[14px]">加载知识库...</span>
        </div>
      </div>
    )
  }

  if (!blogger) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center bg-[#FAFAFA]">
        <div className="text-center">
          <p className="text-[#666]">博主不存在</p>
          <Button onClick={onBack} variant="outline" className="mt-4">返回列表</Button>
        </div>
      </div>
    )
  }

  const displayContent = activeView === 'master' 
    ? blogger.master_summary 
    : activeVideo?.summary || activeVideo?.transcript || '该视频暂无AI总结内容'

  const displayTitle = activeView === 'master' 
    ? `${blogger.nickname} 知识体系大全`
    : activeVideo?.title || '无标题'

  return (
    <div className="flex h-[calc(100vh-64px)] bg-[#FAFAFA]">
      {/* 左侧边栏 */}
      <div className="flex w-72 shrink-0 flex-col border-r border-[#E8E8E8] bg-white">
        <div className="border-b border-[#F0F0F0] px-5 py-4">
          <button
            onClick={onBack}
            className="mb-3 flex items-center gap-1 text-[13px] text-[#888] transition-colors hover:text-[#2C5FFF]"
          >
            <ArrowLeft size={14} />
            返回博主列表
          </button>
          <h2 className="text-[15px] font-semibold text-[#1A1A1A]">{blogger.nickname}</h2>
          {blogger.signature && (
            <p className="mt-0.5 truncate text-[12px] text-[#999]">{blogger.signature}</p>
          )}
          <div className="mt-2 flex gap-3 text-[11px] text-[#999]">
            <span>{formatNumber(blogger.follower_count)} 粉丝</span>
            <span>·</span>
            <span>{blogger.processed_videos}/{blogger.total_videos} 视频</span>
          </div>
        </div>

        {/* 搜索 */}
        <div className="px-4 py-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#BBB]" />
            <Input
              placeholder="搜索视频..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="h-8 pl-9 border-[#E8E8E8] bg-[#FAFAFA] text-[12px] placeholder:text-[#BBB] focus:border-[#2C5FFF]"
            />
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="px-2 pb-4">
            {/* 综合大文档 */}
            {blogger.master_summary && (
              <>
                <p className="px-3 py-2 text-[11px] font-medium text-[#999]">综合文档</p>
                <button
                  onClick={() => { setActiveView('master'); setTab('doc') }}
                  className={`flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors ${
                    activeView === 'master' ? 'bg-[#EEF4FF]' : 'hover:bg-[#F8F9FC]'
                  }`}
                >
                  <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
                    activeView === 'master' ? 'bg-[#2C5FFF]' : 'bg-[#F0F2F7]'
                  }`}>
                    <Home size={12} className={activeView === 'master' ? 'text-white' : 'text-[#888]'} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className={`truncate text-[13px] ${
                      activeView === 'master' ? 'font-medium text-[#2C5FFF]' : 'text-[#333]'
                    }`}>
                      知识体系大全
                    </p>
                    <div className="mt-0.5 text-[11px] text-[#AAA]">
                      所有视频综合总结
                    </div>
                  </div>
                </button>
              </>
            )}

            {/* 视频列表 */}
            <p className="px-3 py-2 text-[11px] font-medium text-[#999]">
              视频解析 · {filteredVideos.length} 篇
            </p>
            {filteredVideos.map((video) => (
              <button
                key={video.id}
                onClick={() => {
                  setActiveView('video')
                  setActiveVideoId(video.id)
                  setTab('doc')
                }}
                className={`flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors ${
                  activeView === 'video' && activeVideoId === video.id
                    ? 'bg-[#EEF4FF]'
                    : 'hover:bg-[#F8F9FC]'
                }`}
              >
                <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
                  activeView === 'video' && activeVideoId === video.id ? 'bg-[#2C5FFF]' : 'bg-[#F0F2F7]'
                }`}>
                  <FileText size={12} className={
                    activeView === 'video' && activeVideoId === video.id ? 'text-white' : 'text-[#888]'
                  } />
                </div>
                <div className="min-w-0 flex-1">
                  <p className={`line-clamp-2 text-[13px] leading-snug ${
                    activeView === 'video' && activeVideoId === video.id
                      ? 'font-medium text-[#2C5FFF]'
                      : 'text-[#333]'
                  }`}>
                    {video.title || '无标题'}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-[#AAA]">
                    {video.duration > 0 && <span>{formatDuration(video.duration)}</span>}
                    {video.digg_count > 0 && (
                      <>
                        {video.duration > 0 && <span>·</span>}
                        <span>{formatNumber(video.digg_count)} 赞</span>
                      </>
                    )}
                    {video.status !== 'summarized' && (
                      <Badge variant="outline" className="h-4 px-1 text-[10px] text-orange-500 border-orange-200">
                        {video.status === 'failed' ? '失败' : '处理中'}
                      </Badge>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* 右侧主内容区 */}
      <div className="flex flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-[#E8E8E8] bg-white px-8">
          <div className="flex gap-6">
            <button
              onClick={() => setTab('doc')}
              className={`flex items-center gap-2 border-b-2 py-3.5 text-[13px] font-medium transition-colors ${
                tab === 'doc' ? 'border-[#2C5FFF] text-[#2C5FFF]' : 'border-transparent text-[#666] hover:text-[#333]'
              }`}
            >
              <BookOpen size={15} />
              知识文档
            </button>
            <button
              onClick={() => setTab('qa')}
              className={`flex items-center gap-2 border-b-2 py-3.5 text-[13px] font-medium transition-colors ${
                tab === 'qa' ? 'border-[#2C5FFF] text-[#2C5FFF]' : 'border-transparent text-[#666] hover:text-[#333]'
              }`}
            >
              <MessageSquare size={15} />
              AI 问答
            </button>
          </div>

          {tab === 'doc' && (
            <div className="flex items-center gap-3 text-[12px] text-[#999]">
              {activeView === 'video' && activeVideo && (
                <>
                  <span className="flex items-center gap-1">
                    <Clock size={12} />
                    {formatDate(activeVideo.create_time)}
                  </span>
                  <Badge variant="outline" className="border-[#E0E0E0] bg-[#F8F9FC] text-[11px] text-[#666]">
                    {formatNumber(activeVideo.digg_count)} 点赞
                  </Badge>
                </>
              )}
              {activeView === 'master' && (
                <Badge className="border-[#2C5FFF]/20 bg-[#EEF4FF] text-[11px] text-[#2C5FFF]">
                  综合总结
                </Badge>
              )}
            </div>
          )}
        </div>

        {tab === 'doc' ? (
          <ScrollArea className="flex-1">
            <div className="mx-auto max-w-[800px] px-12 py-10">
              <article className="doc-content">
                {/* 标题 */}
                <div className="mb-8">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    {activeView === 'master' ? (
                      <>
                        <span className="feishu-tag feishu-tag-blue">综合文档</span>
                        {blogger.master_keywords && blogger.master_keywords.slice(0, 5).map((kw, i) => (
                          <span key={i} className="feishu-tag feishu-tag-gray">{kw}</span>
                        ))}
                      </>
                    ) : activeVideo ? (
                      <>
                        <span className="feishu-tag feishu-tag-blue">视频解析</span>
                        {activeVideo.topics && activeVideo.topics.slice(0, 3).map((t, i) => (
                          <span key={i} className="feishu-tag feishu-tag-orange">{t}</span>
                        ))}
                      </>
                    ) : null}
                  </div>
                  <h1 className="!mt-0 !mb-2 text-[26px] font-bold leading-tight text-[#1A1A1A]">
                    {displayTitle}
                  </h1>
                  <p className="text-[13px] text-[#999]">
                    {blogger.nickname}
                    {activeView === 'video' && activeVideo?.create_time && ` · ${formatDate(activeVideo.create_time)}`}
                  </p>
                </div>

                {/* 核心要点（单视频模式） */}
                {activeView === 'video' && activeVideo?.key_points && activeVideo.key_points.length > 0 && (
                  <div className="mb-8 rounded-lg border border-[#E8F0FE] bg-[#F5F8FF] p-5">
                    <h3 className="mb-3 text-[14px] font-semibold text-[#2C5FFF]">核心要点</h3>
                    <ul className="space-y-2 text-[14px] text-[#333]">
                      {activeVideo.key_points.map((kp, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#2C5FFF] text-[11px] font-medium text-white">
                            {i + 1}
                          </span>
                          <span>{kp}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* 金句/可操作建议 */}
                {activeView === 'video' && activeVideo?.takeaways && (
                  <div className="mb-8 rounded-lg border border-[#E6F7EF] bg-[#F2FBF6] p-5">
                    <h3 className="mb-3 text-[14px] font-semibold text-[#00A870]">金句与实操建议</h3>
                    <div 
                      className="text-[14px] leading-relaxed text-[#333]"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(activeVideo.takeaways) }}
                    />
                  </div>
                )}

                {/* 正文内容 */}
                <div 
                  className="text-[15px] leading-[1.8] text-[#333]"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(displayContent) }}
                />

                {/* 底部 */}
                <div className="mt-12 border-t border-[#EEE] pt-6">
                  <p className="text-[12px] text-[#AAA]">
                    本文由 AI 从抖音视频内容自动分析生成，仅供学习参考
                  </p>
                </div>
              </article>
            </div>
          </ScrollArea>
        ) : (
          <div className="flex flex-1 flex-col">
            <div className="border-b border-[#E8E8E8] bg-white px-8 py-5">
              <div className="mx-auto max-w-[800px]">
                <p className="mb-2 text-[12px] text-[#999]">
                  基于 {blogger.nickname} 的视频内容，向 AI 提问
                </p>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Input
                      placeholder="输入你的问题..."
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
                      className="h-11 border-[#E0E0E0] pr-12 text-[14px] focus:border-[#2C5FFF] focus:ring-2 focus:ring-[#2C5FFF]/10"
                    />
                    <Button
                      onClick={handleAsk}
                      disabled={asking || !question.trim()}
                      className="absolute right-1 top-1/2 h-9 -translate-y-1/2 gap-1.5 bg-[#2C5FFF] text-[13px] hover:bg-[#2555E8]"
                    >
                      {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                      {asking ? '思考中' : '提问'}
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            <ScrollArea className="flex-1">
              <div className="mx-auto max-w-[800px] px-8 py-6">
                {!answer && !asking ? (
                  <div className="flex flex-col items-center justify-center py-20 text-center">
                    <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EEF4FF]">
                      <Sparkles size={26} className="text-[#2C5FFF]" />
                    </div>
                    <h3 className="mb-2 text-[16px] font-medium text-[#333]">开始智能学习</h3>
                    <p className="max-w-md text-[13px] text-[#999]">
                      输入你的问题，AI 将基于博主的视频内容为你解答
                    </p>
                  </div>
                ) : (
                  <div className="space-y-6">
                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#F0F2F7]">
                        <MessageSquare size={14} className="text-[#666]" />
                      </div>
                      <div className="flex-1 pt-1">
                        <p className="text-[14px] text-[#333]">{question}</p>
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EEF4FF]">
                        <Sparkles size={14} className="text-[#2C5FFF]" />
                      </div>
                      <div className="flex-1">
                        {asking ? (
                          <div className="flex items-center gap-2 pt-1 text-[14px] text-[#999]">
                            <Loader2 size={14} className="animate-spin" />
                            AI 正在思考...
                          </div>
                        ) : (
                          <Card className="border-[#E8E8E8] bg-white shadow-sm">
                            <CardContent className="p-5">
                              <div className="doc-content text-[14px] leading-relaxed">
                                <div dangerouslySetInnerHTML={{ __html: answer.replace(/\n/g, '<br/>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>') }} />
                              </div>
                              {sources.length > 0 && (
                                <div className="mt-5 border-t border-[#F0F0F0] pt-4">
                                  <p className="mb-2 text-[12px] font-medium text-[#999]">参考来源（{sources.length}）</p>
                                  <div className="space-y-1.5">
                                    {sources.slice(0, 3).map((s, i) => (
                                      <div key={i} className="flex items-start gap-2 rounded-md bg-[#FAFAFA] px-3 py-2 text-[12px] text-[#666]">
                                        <ChevronRight size={12} className="mt-0.5 shrink-0 text-[#CCC]" />
                                        <span className="line-clamp-2">{s.content?.slice(0, 80)}...</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </CardContent>
                          </Card>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>
    </div>
  )
}

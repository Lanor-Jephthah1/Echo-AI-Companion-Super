import { useState, useEffect, useRef } from 'react';
import { rpcCall, streamCall } from './api';
import { Button } from './components/ui/button';
import { Card, CardContent } from './components/ui/card';
import { Textarea } from './components/ui/textarea';
import { ScrollArea } from './components/ui/scroll-area';
import { Spinner } from './components/ui/spinner';
import { Badge } from './components/ui/badge';
import { Switch } from './components/ui/switch';
import { Plus, MessageSquare, Trash2, Send, Bot, User, Menu, X, HeartPulse, Sparkles, TrendingUp, TrendingDown, Moon, Sun, Gauge, Flame, ScrollText, SlidersHorizontal, Smile, Copy, Check, Share2, Mic, MicOff, Pin } from 'lucide-react';
import { cn } from './lib/utils';

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface Thread {
  id: string;
  title: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

interface ThreadSummary {
  title: string;
  message_count: number;
  summary: string;
  talked_about: string[];
  learned: string[];
  generated_at: string;
  source: 'ai' | 'fallback' | 'empty';
  error?: string;
}

interface SharedImportResponse {
  thread?: Thread;
  readonly?: boolean;
  reason?: string;
  error?: string;
}

interface PinnedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

type SpeechRecognitionEventLite = {
  resultIndex: number;
  results: ArrayLike<
    ArrayLike<{ transcript: string }> & {
      isFinal?: boolean;
    }
  >;
};

type SpeechRecognitionInstanceLite = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLite) => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionCtorLite = new () => SpeechRecognitionInstanceLite;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtorLite;
    webkitSpeechRecognition?: SpeechRecognitionCtorLite;
  }
}

const THREADS_CACHE_KEY = 'echo_threads_cache_v1';
const ACTIVE_THREAD_CACHE_KEY = 'echo_active_thread_v1';
const THEME_CACHE_KEY = 'echo_theme_v1';
const SEND_ENTER_CACHE_KEY = 'echo_send_enter_v1';
const COMPACT_SIDEBAR_CACHE_KEY = 'echo_compact_sidebar_v1';
const PINNED_CACHE_KEY = 'echo_pinned_messages_v1';
const EMOJI_OPTIONS = [
  "\u{1F600}", // grinning face
  "\u{1F601}", // beaming face
  "\u{1F602}", // tears of joy
  "\u{1F923}", // rolling on floor laughing
  "\u{1F60A}", // smiling face
  "\u{1F60D}", // heart eyes
  "\u{1F973}", // partying face
  "\u{1F60E}", // sunglasses
  "\u{1F914}", // thinking face
  "\u{1F64F}", // folded hands
  "\u{1F525}", // fire
  "\u{1F4AA}", // flexed biceps
  "\u{2764}\u{FE0F}", // red heart
  "\u{1F4AF}", // hundred points
  "\u{2728}", // sparkles
  "\u{1F3AF}", // bullseye
  "\u{1F64C}", // raising hands
  "\u{1F91D}", // handshake
  "\u{1F605}", // sweat smile
  "\u{1F634}", // sleeping face
  "\u{1F622}", // crying face
  "\u{1F917}", // hugging face
  "\u{1F4A1}", // light bulb
  "\u{1F9E0}" // brain
];

type SentimentInsight = {
  score: number;
  label: string;
  energy: number;
};

const SENTIMENT_LEXICON: Record<string, number> = {
  happy: 1.8, great: 1.7, awesome: 2.0, amazing: 2.1, good: 1.1, love: 2.0, excited: 1.8, calm: 1.2, grateful: 1.5, better: 1.0,
  hopeful: 1.3, proud: 1.4, focused: 1.1, motivated: 1.4, peaceful: 1.6, confident: 1.5, nice: 0.9,
  sad: -1.8, angry: -1.8, depressed: -2.3, hate: -1.9, upset: -1.5, stressed: -1.9, anxious: -1.8, tired: -1.2, lonely: -2.0,
  worried: -1.5, overwhelmed: -2.0, scared: -1.7, hurt: -1.6, bad: -1.1, terrible: -2.2, empty: -1.9, exhausted: -1.8,
};

const INTENSIFIERS = new Set(['very', 'really', 'extremely', 'super', 'so', 'too']);
const NEGATIONS = new Set(['not', "don't", "didn't", "isn't", "wasn't", 'never', 'no']);

function average(nums: number[]): number {
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function analyzeSentiment(text: string): SentimentInsight {
  const raw = (text || '').trim();
  const t = raw.toLowerCase();
  const crisis = ['suicide', 'kill myself', 'self harm', 'end my life', 'want to die'];
  if (crisis.some((w) => t.includes(w))) {
    return { score: -3, label: 'Crisis', energy: 1 };
  }

  const tokens = t.match(/[a-z']+/g) || [];
  let score = 0;
  let hitCount = 0;

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    const base = SENTIMENT_LEXICON[token];
    if (!base) continue;
    hitCount += 1;
    let weight = base;
    const prev = tokens[i - 1];
    if (prev && INTENSIFIERS.has(prev)) weight *= 1.35;
    if (prev && NEGATIONS.has(prev)) weight *= -1;
    score += weight;
  }

  const exclamations = (raw.match(/!/g) || []).length;
  const questionMarks = (raw.match(/\?/g) || []).length;
  if (score > 0) score += exclamations * 0.12;
  if (score < 0) score -= exclamations * 0.12;
  if (hitCount === 0) {
    if (t.includes('thank')) score += 0.8;
    if (t.includes('help me') || t.includes('i need help')) score -= 0.8;
    if (t.includes('haha') || t.includes('lol')) score += 0.5;
  }
  score -= questionMarks * 0.03;
  score = Math.max(-3, Math.min(3, score));

  const absScore = Math.abs(score);
  const label = score <= -2 ? 'Heavy' : score < -0.5 ? 'Low' : score < 0.6 ? 'Steady' : score < 1.8 ? 'Positive' : 'Elevated';
  const energy = Math.min(1, absScore / 2.4 + Math.min(0.3, exclamations * 0.06));
  return { score, label, energy };
}

function buildSparklinePath(values: number[], width = 180, height = 44): string {
  if (values.length === 0) return '';
  const min = -3;
  const max = 3;
  const stepX = values.length === 1 ? 0 : width / (values.length - 1);
  const points = values.map((v, i) => {
    const normalized = (v - min) / (max - min);
    const y = height - normalized * height;
    const x = i * stepX;
    return `${x},${y}`;
  });
  return `M${points.join(' L')}`;
}

export default function App() {
  const isShareView =
    typeof window !== 'undefined' &&
    (new URLSearchParams(window.location.search).has('share') || window.location.pathname.startsWith('/shared/'));
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth >= 1024;
  });
  const [streamingMessage, setStreamingMessage] = useState('');
  const [status, setStatus] = useState('');
  const [showPulse, setShowPulse] = useState(false);
  const [sendOnEnter, setSendOnEnter] = useState(() => {
    if (typeof window === 'undefined') return true;
    const saved = localStorage.getItem(SEND_ENTER_CACHE_KEY);
    return saved !== 'false';
  });
  const [compactSidebar, setCompactSidebar] = useState(() => {
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(COMPACT_SIDEBAR_CACHE_KEY) === 'true';
  });
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [threadSummary, setThreadSummary] = useState<ThreadSummary | null>(null);
  const [summaryError, setSummaryError] = useState('');
  const [inputFocused, setInputFocused] = useState(false);
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceHint, setVoiceHint] = useState('');
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [pinnedByThread, setPinnedByThread] = useState<Record<string, PinnedMessage[]>>(() => {
    if (typeof window === 'undefined') return {};
    try {
      const raw = localStorage.getItem(PINNED_CACHE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const [shareLoading, setShareLoading] = useState(false);
  const [sharedMode, setSharedMode] = useState(false);
  const [sharedReason, setSharedReason] = useState('');
  const [isTopChromeVisible, setIsTopChromeVisible] = useState(true);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof window === 'undefined') return 'light';
    const saved = localStorage.getItem(THEME_CACHE_KEY);
    return saved === 'dark' ? 'dark' : 'light';
  });

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognitionInstanceLite | null>(null);
  const speechCommittedRef = useRef('');
  const lastVoiceChunkRef = useRef('');
  const lastVoiceChunkAtRef = useRef(0);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const lastChatScrollTopRef = useRef(0);
  const scrollDirectionBudgetRef = useRef(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const audioUnlockedRef = useRef(false);

  const getAudioContext = () => {
    if (typeof window === 'undefined') return null;
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtxRef.current) {
      audioCtxRef.current = new Ctx();
    }
    return audioCtxRef.current;
  };

  const unlockAudio = async () => {
    const ctx = getAudioContext();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
      try {
        await ctx.resume();
      } catch {}
    }
    audioUnlockedRef.current = ctx.state === 'running';
  };

  const playAiSound = (kind: 'send' | 'start' | 'done' | 'error') => {
    const ctx = getAudioContext();
    if (!ctx || !audioUnlockedRef.current) return;
    const now = ctx.currentTime;
    const freqs =
      kind === 'send'
        ? [520, 660]
        : kind === 'start'
        ? [660, 770]
        : kind === 'done'
          ? [720, 860, 980]
          : [260, 220];
    const total = kind === 'done' ? 0.22 : kind === 'send' ? 0.1 : 0.14;
    const step = total / freqs.length;
    freqs.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = kind === 'error' ? 'triangle' : 'sine';
      osc.frequency.setValueAtTime(freq, now + i * step);
      gain.gain.setValueAtTime(0.0001, now + i * step);
      gain.gain.exponentialRampToValueAtTime(0.05, now + i * step + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + (i + 1) * step);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + i * step);
      osc.stop(now + (i + 1) * step);
    });
  };

  useEffect(() => {
    console.log("RENDER_SUCCESS");
    const params = new URLSearchParams(window.location.search);
    const key = params.get('key');
    const shareIdFromQuery = params.get('share');
    const shareIdFromPath = window.location.pathname.startsWith('/shared/')
      ? decodeURIComponent(window.location.pathname.replace('/shared/', '').trim())
      : '';
    const shareId = (shareIdFromQuery || shareIdFromPath || '').trim();
    if (key === 'echoo' && window.location.pathname !== '/admin') {
      window.location.replace(`/admin?key=${encodeURIComponent(key)}`);
      return;
    }

    if (shareId) {
      handleImportSharedThread(shareId);
      return;
    }
    const cachedThreads = localStorage.getItem(THREADS_CACHE_KEY);
    const cachedActive = localStorage.getItem(ACTIVE_THREAD_CACHE_KEY);
    if (cachedThreads) {
      try {
        const parsed = JSON.parse(cachedThreads);
        if (Array.isArray(parsed)) setThreads(parsed);
      } catch {}
    }
    if (cachedActive) setActiveThreadId(cachedActive);
    fetchThreads();
  }, []);

  useEffect(() => {
    const onUserGesture = () => {
      void unlockAudio();
    };
    window.addEventListener('pointerdown', onUserGesture, { passive: true });
    window.addEventListener('keydown', onUserGesture);
    return () => {
      window.removeEventListener('pointerdown', onUserGesture);
      window.removeEventListener('keydown', onUserGesture);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Rec) {
      setSpeechSupported(false);
      return;
    }
    setSpeechSupported(true);
    const rec = new Rec();
    rec.lang = 'en-US';
    rec.interimResults = false;
    rec.continuous = false;
    rec.onstart = () => {
      setIsRecording(true);
      setVoiceHint('Listening...');
      speechCommittedRef.current = '';
      lastVoiceChunkRef.current = '';
      lastVoiceChunkAtRef.current = 0;
    };
    rec.onend = () => {
      setIsRecording(false);
      setVoiceHint((prev) => (prev === 'Listening...' ? 'Voice input stopped.' : prev));
    };
    rec.onerror = () => {
      setIsRecording(false);
      setVoiceHint('Voice input failed. You can type instead.');
    };
    rec.onresult = (event: SpeechRecognitionEventLite) => {
      let transcript = '';
      const start = Math.max(0, Number(event.resultIndex || 0));
      for (let i = start; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result?.isFinal === false) continue;
        const alt = result[0];
        if (alt?.transcript) transcript += `${alt.transcript} `;
      }
      const cleaned = transcript.replace(/\s+/g, ' ').trim();
      if (!cleaned) return;

      // Some browsers return cumulative transcripts in repeated callbacks.
      // Keep only the new delta that wasn't already committed in this recording session.
      const committed = speechCommittedRef.current;
      let delta = cleaned;
      if (committed && cleaned.startsWith(committed)) {
        delta = cleaned.slice(committed.length).trim();
      } else if (committed && committed.startsWith(cleaned)) {
        delta = '';
      }
      if (!delta) return;

      const now = Date.now();
      if (
        delta.toLowerCase() === lastVoiceChunkRef.current.toLowerCase() &&
        now - lastVoiceChunkAtRef.current < 1800
      ) {
        return;
      }

      lastVoiceChunkRef.current = delta;
      lastVoiceChunkAtRef.current = now;
      speechCommittedRef.current = committed ? `${committed} ${delta}`.trim() : cleaned;
      setInput((prev) => `${prev}${prev ? ' ' : ''}${delta}`);
      setVoiceHint('Transcribed voice to text.');
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        textareaRef.current.style.height = '44px';
        textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 128)}px`;
      });
    };
    recognitionRef.current = rec;
    return () => {
      try {
        rec.stop();
      } catch {}
      recognitionRef.current = null;
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') root.classList.add('dark');
    else root.classList.remove('dark');
    localStorage.setItem(THEME_CACHE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [threads, streamingMessage]);

  useEffect(() => {
    if (isShareView || sharedMode) return;
    localStorage.setItem(THREADS_CACHE_KEY, JSON.stringify(threads));
  }, [threads, isShareView, sharedMode]);

  useEffect(() => {
    if (isShareView || sharedMode) return;
    if (activeThreadId) {
      localStorage.setItem(ACTIVE_THREAD_CACHE_KEY, activeThreadId);
    } else {
      localStorage.removeItem(ACTIVE_THREAD_CACHE_KEY);
    }
  }, [activeThreadId, isShareView, sharedMode]);

  useEffect(() => {
    setThreadSummary(null);
    setSummaryError('');
    setShowPulse(false);
    setIsTopChromeVisible(true);
    lastChatScrollTopRef.current = 0;
  }, [activeThreadId]);

  useEffect(() => {
    localStorage.setItem(SEND_ENTER_CACHE_KEY, String(sendOnEnter));
  }, [sendOnEnter]);

  useEffect(() => {
    localStorage.setItem(COMPACT_SIDEBAR_CACHE_KEY, String(compactSidebar));
  }, [compactSidebar]);

  useEffect(() => {
    localStorage.setItem(PINNED_CACHE_KEY, JSON.stringify(pinnedByThread));
  }, [pinnedByThread]);
  const fetchThreads = async () => {
    console.log("[FETCH_START] get_threads");
    try {
      const data = await rpcCall({ func: 'get_threads', args: {} });
      if (Array.isArray(data)) {
        if (data.length > 0) {
          setThreads(data);
          setActiveThreadId((prev) => {
            if (prev && data.some((t: Thread) => t.id === prev)) return prev;
            const cached = localStorage.getItem(ACTIVE_THREAD_CACHE_KEY);
            if (cached && data.some((t: Thread) => t.id === cached)) return cached;
            return data[0].id;
          });
          return;
        }
        if (!isShareView && !sharedMode) {
          const firstThread = await rpcCall({ func: 'create_thread', args: { title: "New Conversation" } });
          setThreads([firstThread]);
          setActiveThreadId(firstThread.id);
        }
      }
    } catch (err) {
      console.error("[FETCH_ERROR]", err);
    }
  };

  const handleCreateThread = async () => {
    if (sharedMode) {
      setStatus(sharedReason || "Shared chats are read-only.");
      return;
    }
    const current = threads.find(t => t.id === activeThreadId);
    if (current && current.messages.length === 0) {
      setStatus("Use the current chat first before creating another.");
      return;
    }
    console.log("[ACTION] create_thread");
    try {
      const newThread = await rpcCall({ func: 'create_thread', args: { title: "New Conversation" } });
      setThreads([newThread, ...threads]);
      setActiveThreadId(newThread.id);
      if (window.innerWidth < 768) setIsSidebarOpen(false);
    } catch (err) {
      console.error("[ACTION_ERROR]", err);
    }
  };

  const handleDeleteThread = async (id: string, e: React.MouseEvent) => {
    if (sharedMode) {
      setStatus(sharedReason || "Shared chats are read-only.");
      return;
    }
    e.stopPropagation();
    console.log("[ACTION] delete_thread", id);
    try {
      await rpcCall({ func: 'delete_thread', args: { thread_id: id } });
      const updatedThreads = threads.filter(t => t.id !== id);
      setThreads(updatedThreads);
      if (activeThreadId === id) {
        setActiveThreadId(updatedThreads.length > 0 ? updatedThreads[0].id : null);
      }
    } catch (err) {
      console.error("[ACTION_ERROR]", err);
    }
  };

  const handleSendMessage = async () => {
    if (sharedMode) {
      setStatus(sharedReason || "This shared chat is read-only.");
      return;
    }
    if (!input.trim() || !activeThreadId || loading) return;

    const userMsg = input.trim();
    setInput('');
    setShowEmojiPicker(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
    }
    setLoading(true);
    setStreamingMessage('');
    setStatus('');
    playAiSound('send');

    // Optimistically update UI
    setThreads(prev => prev.map(t => {
      if (t.id === activeThreadId) {
        return {
          ...t,
          messages: [...t.messages, { role: 'user', content: userMsg }]
        };
      }
      return t;
    }));

    try {
      console.log("[STREAM_START] chat_streaming");
      let fullContent = '';
      let playedStartSound = false;
      
      await streamCall({
        func: 'chat_streaming',
        args: { thread_id: activeThreadId, message: userMsg },
        onChunk: (chunk) => {
          if (chunk.type === 'status') {
            setStatus(chunk.message);
          } else if (chunk.type === 'chunk') {
            if (!playedStartSound) {
              playedStartSound = true;
              playAiSound('start');
            }
            fullContent += chunk.content;
            setStreamingMessage(fullContent);
            setStatus('');
          } else if (chunk.type === 'result') {
            if (fullContent.trim()) {
              playAiSound('done');
            }
            // Finalize thread update (title might have changed)
            setThreads(prev => prev.map(t => {
              if (t.id === activeThreadId) {
                return {
                  ...t,
                  title: chunk.data.title,
                  messages: [...t.messages, { role: 'assistant', content: fullContent }]
                };
              }
              return t;
            }));
            setStreamingMessage('');
          } else if (chunk.type === 'error') {
            console.error("[STREAM_ERROR_CHUNK]", chunk.message);
            playAiSound('error');
            setStatus(`Error: ${chunk.message}`);
          }
        },
        onError: (err) => {
          console.error("[STREAM_ERROR]", err);
          playAiSound('error');
          setStatus("Sorry, I encountered an error.");
        }
      });
    } catch (err) {
      console.error("[SEND_ERROR]", err);
    } finally {
      setLoading(false);
    }
  };

  const activeThread = threads.find(t => t.id === activeThreadId);
  const blockNewChat = !!activeThread && activeThread.messages.length === 0;
  const userMsgs = (activeThread?.messages || []).filter(m => m.role === 'user').map(m => m.content);
  const assistantMsgs = (activeThread?.messages || []).filter(m => m.role === 'assistant').map(m => m.content);
  const userAnalyses = userMsgs.slice(-12).map(analyzeSentiment);
  const moodSeries = userAnalyses.map(s => s.score);
  const moodAvg = average(moodSeries);
  const moodEnergy = average(userAnalyses.map(s => s.energy));
  const latestSent = userAnalyses.length ? userAnalyses[userAnalyses.length - 1] : { score: 0, label: 'Steady', energy: 0 };
  const headWindow = moodSeries.slice(0, Math.max(1, Math.floor(moodSeries.length / 2)));
  const tailWindow = moodSeries.slice(-Math.max(1, Math.floor(moodSeries.length / 2)));
  const moodTrend = average(tailWindow) - average(headWindow);
  const moodLabel = moodAvg <= -1.3 ? 'Heavy' : moodAvg < -0.4 ? 'Low' : moodAvg < 0.35 ? 'Steady' : moodAvg < 1.1 ? 'Positive' : 'Elevated';
  const animationProfile = moodAvg <= -0.9 ? 'anim-calm' : moodAvg >= 0.95 ? 'anim-energetic' : 'anim-balanced';
  const sparkline = buildSparklinePath(moodSeries.length ? moodSeries : [0]);
  const totalMessages = threads.reduce((acc, t) => acc + (t.messages?.length || 0), 0);
  const recentActive = threads.length ? new Date(threads[0].updated_at || threads[0].created_at || '').toLocaleString() : 'No activity yet';
  const lastAssistantPreview = (assistantMsgs[assistantMsgs.length - 1] || '').slice(0, 90);

  const memoryCards = [
    {
      id: 'steps',
      label: 'Weekly Steps',
      prompt: 'Based on what you know about me, give me 3 practical steps I should take this week.',
    },
    {
      id: 'mood',
      label: 'Mood Insight',
      prompt: `Summarize my current emotional pattern as ${moodLabel.toLowerCase()} and give one actionable habit for today.`,
    },
    {
      id: 'continue',
      label: 'Continue',
      prompt: lastAssistantPreview
        ? `Continue from your last point: "${lastAssistantPreview}" and give me the clearest next action.`
        : 'Continue from where we stopped and help me finish my highest-priority task today.',
    },
  ];
  const activePins = activeThreadId ? (pinnedByThread[activeThreadId] || []) : [];

  const handleApplyMemoryPrompt = (prompt: string) => {
    if (sharedMode) {
      setStatus(sharedReason || 'Shared chats are read-only.');
      return;
    }
    setInput(prompt);
    requestAnimationFrame(() => {
      if (!textareaRef.current) return;
      textareaRef.current.focus();
      textareaRef.current.style.height = '44px';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 128)}px`;
    });
  };

  const handleTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    if (window.innerWidth >= 768) return;
    const t = e.touches[0];
    touchStartRef.current = { x: t.clientX, y: t.clientY };
  };

  const handleTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    if (window.innerWidth >= 768) return;
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    const mostlyHorizontal = Math.abs(dx) > Math.abs(dy) * 1.2;
    if (!mostlyHorizontal || Math.abs(dy) > 80) return;
    if (dx > 72 && !isSidebarOpen) {
      setIsSidebarOpen(true);
      return;
    }
    if (dx < -72 && isSidebarOpen) {
      setIsSidebarOpen(false);
    }
  };

  const handleChatViewportScroll: React.UIEventHandler<HTMLDivElement> = (e) => {
    const node = e.currentTarget;
    const top = node.scrollTop;
    const prev = lastChatScrollTopRef.current;
    const delta = top - prev;
    lastChatScrollTopRef.current = top;
    if (Math.abs(delta) < 2) return;

    if (top <= 8) {
      setIsTopChromeVisible(true);
      scrollDirectionBudgetRef.current = 0;
      return;
    }

    // Hysteresis budget to avoid flicker on tiny direction changes.
    const nextBudget = scrollDirectionBudgetRef.current + delta;
    const clamped = Math.max(-64, Math.min(64, nextBudget));
    scrollDirectionBudgetRef.current = clamped;
    const threshold = 20;

    if (!isTopChromeVisible && clamped >= threshold) {
      setIsTopChromeVisible(true);
      scrollDirectionBudgetRef.current = 0;
      return;
    }
    if (isTopChromeVisible && clamped <= -threshold) {
      setIsTopChromeVisible(false);
      scrollDirectionBudgetRef.current = 0;
    }
  };

  const togglePinMessage = (messageId: string, role: 'user' | 'assistant', content: string) => {
    if (!activeThreadId) return;
    setPinnedByThread((prev) => {
      const existing = prev[activeThreadId] || [];
      const has = existing.some((m) => m.id === messageId);
      const nextPins = has
        ? existing.filter((m) => m.id !== messageId)
        : [...existing, { id: messageId, role, content }];
      return { ...prev, [activeThreadId]: nextPins.slice(-12) };
    });
  };

  const jumpToPinnedMessage = (messageId: string) => {
    const node = messageRefs.current[messageId];
    if (!node) return;
    node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const applyReflectivePrompt = () => {
    const prompt = moodAvg <= -1
      ? "I feel heavy right now. Help me calm down step-by-step."
      : moodAvg >= 0.8
        ? "I'm feeling good. Help me channel this energy productively."
        : "Help me reflect on today and identify one useful next step.";
    setInput(prompt);
  };

  const handleSummarizeThread = async () => {
    if (!activeThreadId || summaryLoading) return;
    setSummaryLoading(true);
    setSummaryError('');
    try {
      const result = await rpcCall<ThreadSummary>({ func: 'summarize_thread', args: { thread_id: activeThreadId } });
      if (result && (result as any).error) {
        setSummaryError(String((result as any).error));
        setThreadSummary(null);
      } else {
        setThreadSummary(result);
      }
    } catch (err) {
      console.error('[SUMMARY_ERROR]', err);
      setSummaryError('Could not summarize this chat right now.');
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleInsertEmoji = (emoji: string) => {
    if (!textareaRef.current) {
      setInput((prev) => prev + emoji);
      return;
    }
    const ta = textareaRef.current;
    const start = ta.selectionStart ?? input.length;
    const end = ta.selectionEnd ?? input.length;
    const next = input.slice(0, start) + emoji + input.slice(end);
    setInput(next);
    requestAnimationFrame(() => {
      ta.focus();
      const pos = Math.min(start + emoji.length, next.length);
      ta.selectionStart = pos;
      ta.selectionEnd = pos;
      ta.style.height = '44px';
      ta.style.height = `${Math.min(ta.scrollHeight, 128)}px`;
    });
  };

  const handleToggleRecording = () => {
    if (sharedMode) return;
    const rec = recognitionRef.current;
    if (!rec) {
      setVoiceHint('Voice input not supported on this browser.');
      return;
    }
    try {
      if (isRecording) {
        rec.stop();
      } else {
        setShowEmojiPicker(false);
        rec.start();
      }
    } catch {
      setVoiceHint('Could not start voice input. Please try again.');
    }
  };

  const handleCopyMessage = async (text: string, idx: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(idx);
      setTimeout(() => setCopiedIndex((prev) => (prev === idx ? null : prev)), 1200);
    } catch (e) {
      console.error('Copy failed', e);
    }
  };

  const handleImportSharedThread = async (shareId: string) => {
    try {
      const res = await rpcCall<SharedImportResponse>({
        func: 'import_shared_thread',
        args: { share_id: shareId },
      });
      if (res?.error || !res?.thread) {
        setStatus(res?.error || 'Could not import shared chat.');
        return;
      }
      const thread = res.thread;
      setThreads([thread]);
      setActiveThreadId(thread.id);
      setSharedMode(Boolean(res.readonly));
      setSharedReason(
        res.reason || 'This is a shared read-only snapshot to protect the owner conversation and privacy.'
      );
      setStatus('');
    } catch (err) {
      console.error('[IMPORT_SHARED_ERROR]', err);
      setStatus('Could not import shared chat.');
    }
  };

  const handleShareThread = async () => {
    if (!activeThreadId || shareLoading) return;
    setShareLoading(true);
    try {
      const res = await rpcCall<{ url?: string; error?: string }>({
        func: 'create_share_link',
        args: { thread_id: activeThreadId },
      });
      if (res?.error || !res?.url) {
        setStatus(res?.error || 'Could not create share link.');
        return;
      }
      await navigator.clipboard.writeText(res.url);
      setStatus('Share link copied.');
    } catch (err) {
      console.error('[SHARE_ERROR]', err);
      setStatus('Could not copy share link.');
    } finally {
      setShareLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "chat-shell flex h-screen w-full max-w-full bg-background text-foreground overflow-x-hidden overflow-y-hidden [touch-action:pan-y]",
        animationProfile
      )}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* Mobile Menu Overlay */}
      {!isSidebarOpen && (
        <Button 
          variant="ghost" 
          size="icon" 
          className="fixed top-4 left-4 z-50 md:hidden motion-fade-in"
          onClick={() => setIsSidebarOpen(true)}
        >
          <Menu className="h-6 w-6" />
        </Button>
      )}

      {isSidebarOpen && (
        <button
          type="button"
          aria-label="Close sidebar overlay"
          className="fixed inset-0 z-30 bg-black/35 backdrop-blur-[1px] md:hidden motion-overlay"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={cn(
        "motion-panel sidebar-smooth fixed inset-y-0 left-0 z-40 w-72 bg-card border-r transform transition-transform duration-300 ease-out",
        isSidebarOpen ? "motion-panel-enter" : "",
        isSidebarOpen ? "translate-x-0 opacity-100 shadow-2xl" : "-translate-x-full opacity-0"
      )}>
        <div className="flex flex-col h-full">
          <div className="p-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-primary flex items-center gap-2">
              <div className="bg-primary/10 p-1.5 rounded-lg">
                <img src="/echo-ai-logo.png" alt="Echo AI Logo" className="h-5 w-5" />
              </div>
              Echo AI
            </h1>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                aria-label="Toggle theme"
                title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </Button>
              <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setIsSidebarOpen(false)}>
                <X className="h-5 w-5" />
              </Button>
            </div>
          </div>

          <div className="px-4 mb-4">
            <Button className="w-full justify-start gap-2" variant="outline" onClick={handleCreateThread} disabled={blockNewChat || sharedMode}>
              <Plus className="h-4 w-4" />
              New Chat
            </Button>
          </div>

          <div className="px-4 mb-4">
            <Card className="border-none shadow-premium bg-gradient-to-br from-primary/15 via-card to-card">
              <CardContent className="p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Command Center</p>
                  <Gauge className="h-4 w-4 text-primary" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-md border bg-background/70 p-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Chats</p>
                    <p className="text-sm font-semibold">{threads.length}</p>
                  </div>
                  <div className="rounded-md border bg-background/70 p-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Messages</p>
                    <p className="text-sm font-semibold">{totalMessages}</p>
                  </div>
                </div>
                <div className="rounded-md border bg-background/70 p-2 flex items-center justify-between">
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase">Tone</p>
                    <p className="text-sm font-medium">{moodLabel}</p>
                  </div>
                  <Flame className={cn("h-4 w-4", moodAvg >= 0 ? "text-emerald-600" : moodAvg < 0 ? "text-rose-600" : "text-amber-600")} />
                </div>
                <p className="text-[10px] text-muted-foreground">Latest activity: {recentActive}</p>
              </CardContent>
            </Card>
          </div>

          <ScrollArea className="flex-1 px-4">
            <div className="space-y-1 pb-4">
              {threads.map(thread => (
                <div
                  key={thread.id}
                  onClick={() => {
                    setActiveThreadId(thread.id);
                    if (window.innerWidth < 768) setIsSidebarOpen(false);
                  }}
                  className={cn(
                    "motion-chip group flex items-center justify-between rounded-lg cursor-pointer transition-colors",
                    compactSidebar ? "p-2" : "p-3",
                    activeThreadId === thread.id ? "bg-primary/10 text-primary" : "hover:bg-muted"
                  )}
                >
                  <div className="flex items-center gap-3 overflow-hidden">
                    <MessageSquare className="h-4 w-4 shrink-0" />
                    <span className="truncate text-sm font-medium">{thread.title}</span>
                  </div>
                  {!sharedMode && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity hover:text-destructive"
                      onClick={(e) => handleDeleteThread(thread.id, e)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              {threads.length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No conversations yet
                </div>
              )}
            </div>
          </ScrollArea>

          <div className="border-t px-4 py-3">
            <Card className="border-none shadow-premium">
              <CardContent className="p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Quick Settings</p>
                  <SlidersHorizontal className="h-4 w-4 text-primary" />
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">Send on Enter</p>
                    <p className="text-[11px] text-muted-foreground">Shift + Enter for new line</p>
                  </div>
                  <Switch checked={sendOnEnter} onCheckedChange={setSendOnEnter} />
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">Compact Sidebar</p>
                    <p className="text-[11px] text-muted-foreground">Denser thread list layout</p>
                  </div>
                  <Switch checked={compactSidebar} onCheckedChange={setCompactSidebar} />
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div
        className={cn(
          "flex-1 flex flex-col h-full min-w-0 w-full relative overflow-x-hidden transition-[padding] duration-300 ease-out",
          isSidebarOpen ? "md:pl-72" : "md:pl-0"
        )}
      >
        {/* Header */}
        <header
          className={cn(
            "border-b flex items-center px-3 md:px-6 bg-background/85 backdrop-blur-xl sticky top-0 z-40 shrink-0 transition-all duration-300 ease-out overflow-hidden",
            isTopChromeVisible ? "h-16 opacity-100" : "h-0 opacity-0 border-b-0 pointer-events-none",
            isSidebarOpen ? "opacity-0 pointer-events-none md:opacity-100 md:pointer-events-auto" : ""
          )}
        >
          <div className="flex items-center justify-between w-full gap-3">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <Button
                variant="outline"
                size="icon"
                className="hidden md:inline-flex h-10 w-10 shrink-0"
                onClick={() => setIsSidebarOpen((v) => !v)}
                aria-label={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
                title={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
              >
                <Menu className="h-5 w-5" />
              </Button>
              <div className="md:hidden w-8 shrink-0" /> {/* Spacer for menu button */}
              <h2 className="font-semibold truncate">
                {activeThread ? activeThread.title : "Select a conversation"}
              </h2>
              {activeThread && (
                <Badge variant="secondary" className="ml-1 font-normal text-[10px] uppercase tracking-wider shrink-0 hidden sm:inline-flex">
                  {activeThread.messages.length} messages
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <Button
                size="sm"
                variant="outline"
                className="gap-1 px-2 md:px-3"
                onClick={handleShareThread}
                disabled={!activeThreadId || shareLoading || sharedMode}
              >
                {shareLoading ? <Spinner className="h-3.5 w-3.5" /> : <Share2 className="h-3.5 w-3.5" />}
                <span className="hidden sm:inline">Share</span>
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="gap-1 px-2 md:px-3"
                onClick={handleSummarizeThread}
                disabled={!activeThreadId || summaryLoading}
              >
                {summaryLoading ? <Spinner className="h-3.5 w-3.5" /> : <ScrollText className="h-3.5 w-3.5" />}
                <span className="hidden sm:inline">Summarize</span>
              </Button>
            </div>
          </div>
        </header>
        {sharedMode && activeThread && (
          <div className="px-4 md:px-6 pt-3">
            <Card className="border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700/50">
              <CardContent className="p-3">
                <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
                  Read-only shared chat
                </p>
                <p className="text-xs text-amber-800/90 dark:text-amber-300/90 mt-1">
                  {sharedReason || 'This shared snapshot is locked. You can view and copy messages, but you cannot continue or edit the conversation.'}
                </p>
              </CardContent>
            </Card>
          </div>
        )}
        {activeThread && (
          <div className={cn("px-4 md:px-6 motion-accordion", (threadSummary || summaryError) ? "open" : "")}>
            {(threadSummary || summaryError) && (
            <Card className="motion-fade-up mt-3 border-none shadow-premium bg-gradient-to-r from-card via-card to-primary/5">
              <CardContent className="p-3 md:p-4 space-y-3 max-h-[48vh] overflow-y-auto no-scrollbar pr-1">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold">Conversation Summary</p>
                  {threadSummary && (
                    <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                      {threadSummary.source}
                    </Badge>
                  )}
                </div>
                {summaryError && (
                  <p className="text-sm text-rose-600">{summaryError}</p>
                )}
                {threadSummary && (
                  <>
                    <p className="text-sm leading-relaxed">{threadSummary.summary}</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="rounded-lg border bg-card/70 p-3">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">What They Talked About</p>
                        <ul className="space-y-1 text-sm">
                          {threadSummary.talked_about.map((item, idx) => (
                            <li key={`talked-${idx}`} className="leading-relaxed">- {item}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded-lg border bg-card/70 p-3">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">What Echo Learned</p>
                        <ul className="space-y-1 text-sm">
                          {threadSummary.learned.map((item, idx) => (
                            <li key={`learned-${idx}`} className="leading-relaxed">- {item}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      Based on {threadSummary.message_count} messages
                    </p>
                  </>
                )}
              </CardContent>
            </Card>
            )}
          </div>
        )}
        {activeThread && (
          <div
            className={cn(
              "overflow-hidden transition-all duration-300 ease-out",
              isTopChromeVisible ? "max-h-[460px] opacity-100" : "max-h-0 opacity-0 pointer-events-none"
            )}
          >
            <div className={cn("px-4 md:px-6 motion-accordion", showPulse ? "open" : "")}>
              {showPulse && (
              <Card className="motion-fade-up mt-3 border-none shadow-premium bg-gradient-to-r from-primary/10 via-background to-primary/5">
                <CardContent className="p-3 md:p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <div className="h-8 w-8 rounded-full bg-primary/15 flex items-center justify-center animate-pulse">
                        <HeartPulse className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">Emotion Pulse</p>
                        <p className="text-sm font-semibold">{moodLabel} ({latestSent.label})</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="outline" className="gap-1" onClick={applyReflectivePrompt}>
                        <Sparkles className="h-3.5 w-3.5" />
                        Reflective Prompt
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setShowPulse(false)}>Hide</Button>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
                    <div className="rounded-lg border bg-card/70 p-2">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Current Tone</p>
                      <p className="text-sm font-medium">{moodAvg >= 0 ? '+' : ''}{moodAvg.toFixed(2)}</p>
                    </div>
                    <div className="rounded-lg border bg-card/70 p-2 flex items-center justify-between">
                      <div>
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Trend</p>
                        <p className="text-sm font-medium">{moodTrend >= 0.12 ? 'Rising' : moodTrend <= -0.12 ? 'Dropping' : 'Flat'}</p>
                      </div>
                      {moodTrend >= 0.12 ? <TrendingUp className="h-4 w-4 text-emerald-600" /> : moodTrend <= -0.12 ? <TrendingDown className="h-4 w-4 text-rose-600" /> : <HeartPulse className="h-4 w-4 text-amber-600" />}
                    </div>
                    <div className="rounded-lg border bg-card/70 p-2">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Energy</p>
                      <p className="text-sm font-medium">{Math.round(moodEnergy * 100)}%</p>
                    </div>
                  </div>
                  <div className="mt-2">
                    <svg viewBox="0 0 180 44" className="w-full h-11">
                      <path d="M0,22 L180,22" stroke="hsl(var(--border))" strokeWidth="1" fill="none" />
                      <path d={sparkline} stroke="hsl(var(--primary))" strokeWidth="2.5" fill="none" strokeLinecap="round" />
                    </svg>
                  </div>
                </CardContent>
              </Card>
              )}
            </div>
            {!showPulse && (
              <div className="px-4 md:px-6 pt-2">
                <Button size="sm" variant="ghost" onClick={() => setShowPulse(true)}>Show Emotion Pulse</Button>
              </div>
            )}
          </div>
        )}

        {/* Chat Area */}
        <ScrollArea
          className="responses-stage flex-1 p-4 md:p-6"
          viewportOnScroll={handleChatViewportScroll}
        >
          <div className="responses-track max-w-3xl mx-auto space-y-6 pb-4">
            {!activeThreadId ? (
              <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
                <div className="bg-primary/5 p-6 rounded-full">
                  <Bot className="h-12 w-12 text-primary/40" />
                </div>
                <div className="space-y-2">
                  <h3 className="text-xl font-semibold">Welcome to Echo AI</h3>
                  <p className="text-muted-foreground max-w-sm">
                    A chill, compassionate digital buddy here to listen and chat.
                  </p>
                </div>
                <Button onClick={handleCreateThread}>Start a conversation</Button>
              </div>
            ) : (
              <>
                {/* System / Welcome Message */}
                <div className="flex justify-center mb-8">
                  <div className="bg-muted/50 px-4 py-2 rounded-full text-xs text-muted-foreground">
                    Conversation started on {new Date(activeThread?.created_at || "").toLocaleDateString()}
                  </div>
                </div>

                {activeThread?.messages.map((msg, idx) => {
                  const messageId = `${activeThread?.id || 't'}:${idx}:${msg.role}`;
                  const isPinned = activePins.some((p) => p.id === messageId);
                  return (
                  <div
                    key={idx}
                    ref={(el) => { messageRefs.current[messageId] = el; }}
                    style={{ animationDelay: `${Math.min(idx, 12) * 20}ms` }}
                    className={cn(
                    "message-pop flex w-full gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300",
                    msg.role === 'user' ? "msg-user-enter" : "msg-bot-enter",
                    msg.role === 'user' ? "flex-row-reverse" : "flex-row"
                  )}>
                    <div className={cn(
                      "h-8 w-8 rounded-full flex items-center justify-center shrink-0 shadow-sm",
                      msg.role === 'user' ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                    )}>
                      {msg.role === 'user' ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                    </div>
                    <div className={cn("max-w-[85%] flex flex-col", msg.role === 'user' ? "items-end" : "items-start")}>
                      <Card className={cn(
                        "w-full shadow-premium border-none",
                        msg.role === 'user' ? "bg-primary text-primary-foreground" : "bg-card"
                      )}>
                        <CardContent className="p-3 md:p-4 text-sm leading-relaxed whitespace-pre-wrap">
                          {msg.content}
                        </CardContent>
                      </Card>
                      <div className="mt-1 flex items-center gap-1">
                        {msg.role === 'assistant' && (
                          <button
                            type="button"
                            aria-label="Copy response"
                            className="motion-chip h-7 w-7 rounded-md border border-border/60 bg-background/70 text-foreground inline-flex items-center justify-center hover:bg-background transition-colors"
                            onClick={() => handleCopyMessage(msg.content, idx)}
                          >
                            {copiedIndex === idx ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                          </button>
                        )}
                        {msg.role === 'assistant' && (
                          <button
                            type="button"
                            aria-label="Pin message"
                            className={cn(
                              "motion-chip h-7 w-7 rounded-md border border-border/60 bg-background/70 inline-flex items-center justify-center hover:bg-background transition-colors",
                              isPinned ? "text-primary" : "text-foreground"
                            )}
                            onClick={() => togglePinMessage(messageId, 'assistant', msg.content)}
                          >
                            <Pin className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )})}

                {/* Streaming Assistant Message */}
                {(streamingMessage || status) && (
                  <div className="message-pop flex w-full gap-4 animate-in fade-in duration-200">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                      <Bot className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <Card className="max-w-[85%] shadow-premium border-none bg-card stream-shimmer">
                      <CardContent className="p-3 md:p-4 text-sm leading-relaxed">
                        {status && (
                          <div className="flex items-center gap-2 text-muted-foreground italic">
                            {loading ? (
                              <span className="typing-dots" aria-hidden="true">
                                <span></span><span></span><span></span>
                              </span>
                            ) : null}
                          </div>
                        )}
                        <div className="whitespace-pre-wrap">{streamingMessage}</div>
                      </CardContent>
                    </Card>
                  </div>
                )}
                
                <div ref={scrollRef} />
              </>
            )}
          </div>
        </ScrollArea>

        {activeThreadId && activePins.length > 0 && (
          <div className="px-2 md:px-6 pb-1">
            <div className="max-w-3xl mx-auto overflow-x-auto no-scrollbar">
              <div className="flex items-center gap-1.5 md:gap-2 whitespace-nowrap">
                {activePins.map((pin) => (
                  <button
                    key={pin.id}
                    type="button"
                    onClick={() => jumpToPinnedMessage(pin.id)}
                    className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 hover:bg-primary/10 text-[10px] md:text-xs px-2 md:px-3 py-1 transition-colors"
                    title={pin.content}
                  >
                    <Pin className="h-3 w-3" />
                    <span className="max-w-[180px] md:max-w-[260px] truncate">
                      {pin.content}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeThreadId && !sharedMode && (
          <div className="px-2 md:px-6 pb-1 md:pb-2">
            <div className="max-w-3xl mx-auto overflow-x-auto no-scrollbar">
              <div className="flex items-center gap-1.5 md:gap-2 whitespace-nowrap">
                {memoryCards.map((card) => (
                  <button
                    key={card.id}
                    type="button"
                    onClick={() => handleApplyMemoryPrompt(card.prompt)}
                    className="motion-chip inline-flex items-center rounded-full border border-primary/25 bg-primary/5 hover:bg-primary/10 text-[10px] md:text-xs px-2 md:px-3 py-1 transition-colors"
                    title={card.prompt}
                  >
                    {card.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Input Area */}
        {activeThreadId && (
          <div
            className={cn(
              "p-2 md:p-4 bg-gradient-to-t from-background via-background to-transparent sticky bottom-0 left-0 right-0 z-20 transition-transform duration-300 ease-out",
              inputFocused ? "-translate-y-2 md:translate-y-0" : "translate-y-0"
            )}
          >
            <div className="max-w-3xl mx-auto">
              <div className={cn("relative group input-shell", (inputFocused || input.length > 0) ? "is-active" : "")}>
                <Textarea
                  ref={textareaRef}
                  className="textarea-modern no-scrollbar pr-28 py-2 min-h-[44px] max-h-32 resize-none overflow-y-auto break-words [overflow-wrap:anywhere] bg-card/95 border-none shadow-premium focus-visible:ring-primary/30 rounded-2xl"
                  placeholder={sharedMode ? 'This shared chat is read-only.' : 'How are you feeling today?'}
                  value={input}
                  rows={1}
                  onChange={(e) => {
                    const v = e.target.value;
                    setInput(v);
                    e.target.style.height = '44px';
                    e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`;
                  }}
                  onFocus={() => setInputFocused(true)}
                  onBlur={() => {
                    setInputFocused(false);
                    setTimeout(() => setShowEmojiPicker(false), 120);
                  }}
                  onKeyDown={(e) => {
                    if (sendOnEnter && e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  disabled={loading || sharedMode}
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className={cn("rounded-xl transition-all duration-200", isRecording && "text-rose-500 animate-pulse")}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={handleToggleRecording}
                    aria-label={isRecording ? 'Stop recording' : 'Start voice recording'}
                    title={speechSupported ? (isRecording ? 'Stop recording' : 'Start recording') : 'Voice input not supported on this browser'}
                    disabled={loading || sharedMode || !speechSupported}
                  >
                    {isRecording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="rounded-xl transition-all duration-200"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => setShowEmojiPicker((v) => !v)}
                    aria-label="Open emoji picker"
                    disabled={sharedMode}
                  >
                    <Smile className="h-4 w-4" />
                  </Button>
                  <Button 
                    size="icon" 
                    className="rounded-xl transition-all duration-200"
                    disabled={loading || !input.trim() || sharedMode}
                    onClick={handleSendMessage}
                  >
                    {loading ? <Spinner className="h-4 w-4" /> : <Send className="h-4 w-4" />}
                  </Button>
                </div>
                {showEmojiPicker && (
                  <div className="absolute right-0 bottom-12 w-[260px] rounded-xl border bg-card p-2 shadow-xl z-30">
                    <div className="grid grid-cols-8 gap-1">
                      {EMOJI_OPTIONS.map((emoji) => (
                        <button
                          key={emoji}
                          type="button"
                          className="h-7 w-7 rounded hover:bg-muted text-base"
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => handleInsertEmoji(emoji)}
                        >
                          {emoji}
                        </button>
                      ))}
                    </div>
                    <a
                      href="https://getemoji.com/"
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 block text-[11px] text-primary hover:underline text-right"
                    >
                      More emojis via getemoji.com
                    </a>
                  </div>
                )}
              </div>
              <div className="mt-2 flex items-center justify-between">
                <p className="text-[10px] text-muted-foreground">
                  {sendOnEnter ? 'Enter to send, Shift+Enter for new line' : 'Multi-line mode enabled'}
                </p>
                <p className="text-[10px] text-muted-foreground">{input.length} chars</p>
              </div>
              {(voiceHint || !speechSupported) && (
                <p className="text-[10px] mt-1 text-muted-foreground">
                  {voiceHint || 'Voice input is unavailable on this browser.'}
                </p>
              )}
              <p className="text-[10px] text-center mt-3 text-muted-foreground">
                Echo AI is a compassionate digital buddy. Always consult professionals for serious concerns.
              </p>
              <div className="mt-3 flex items-center justify-center gap-4">
                <a
                  href="mailto:mclanorjephthah@gmail.com"
                  target="_blank"
                  rel="noreferrer"
                  className="social-bounce social-delay-1 text-[18px]"
                  aria-label="Gmail"
                >
                  <i className="fa-solid fa-envelope text-[#EA4335]" />
                </a>
                <a
                  href="https://www.linkedin.com/in/jephthah-kwame-lanor-6b9017262/"
                  target="_blank"
                  rel="noreferrer"
                  className="social-bounce social-delay-2 text-[18px]"
                  aria-label="LinkedIn"
                >
                  <i className="fa-brands fa-linkedin text-[#0A66C2]" />
                </a>
                <a
                  href="https://bsky.app/profile/mclanorjeff.bsky.social"
                  target="_blank"
                  rel="noreferrer"
                  className="social-bounce social-delay-3 text-[18px]"
                  aria-label="Bluesky"
                >
                  <i className="fa-brands fa-bluesky text-[#0085FF]" />
                </a>
                <a
                  href="https://x.com/jeff_lanor"
                  target="_blank"
                  rel="noreferrer"
                  className="social-bounce social-delay-1 text-[18px]"
                  aria-label="X"
                >
                  <i className="fa-brands fa-x-twitter text-[#111111] dark:text-[#f5f5f5]" />
                </a>
                <a
                  href="https://github.com/Lanor-Jephthah1"
                  target="_blank"
                  rel="noreferrer"
                  className="social-bounce social-delay-2 text-[18px]"
                  aria-label="GitHub"
                >
                  <i className="fa-brands fa-github text-[#171515] dark:text-[#f5f5f5]" />
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


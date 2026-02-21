import { useState, useEffect, useRef } from 'react';
import { rpcCall, streamCall } from './api';
import { Button } from './components/ui/button';
import { Card, CardContent } from './components/ui/card';
import { Input } from './components/ui/input';
import { ScrollArea } from './components/ui/scroll-area';
import { Spinner } from './components/ui/spinner';
import { Badge } from './components/ui/badge';
import { Separator } from './components/ui/separator';
import { Plus, MessageSquare, Trash2, Send, Bot, User, Menu, X } from 'lucide-react';
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

export default function App() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [status, setStatus] = useState('');

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    console.log("RENDER_SUCCESS");
    fetchThreads();
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [threads, streamingMessage]);

  const fetchThreads = async () => {
    console.log("[FETCH_START] get_threads");
    try {
      const data = await rpcCall({ func: 'get_threads', args: {} });
      setThreads(data);
      if (data.length > 0 && !activeThreadId) {
        setActiveThreadId(data[0].id);
      }
    } catch (err) {
      console.error("[FETCH_ERROR]", err);
    }
  };

  const handleCreateThread = async () => {
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
    if (!input.trim() || !activeThreadId || loading) return;

    const userMsg = input.trim();
    setInput('');
    setLoading(true);
    setStreamingMessage('');
    setStatus('');

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
      
      await streamCall({
        func: 'chat_streaming',
        args: { thread_id: activeThreadId, message: userMsg },
        onChunk: (chunk) => {
          if (chunk.type === 'status') {
            setStatus(chunk.message);
          } else if (chunk.type === 'chunk') {
            fullContent += chunk.content;
            setStreamingMessage(fullContent);
            setStatus('');
          } else if (chunk.type === 'result') {
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
            setStatus(`Error: ${chunk.message}`);
          }
        },
        onError: (err) => {
          console.error("[STREAM_ERROR]", err);
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

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Mobile Menu Overlay */}
      {!isSidebarOpen && (
        <Button 
          variant="ghost" 
          size="icon" 
          className="fixed top-4 left-4 z-50 md:hidden"
          onClick={() => setIsSidebarOpen(true)}
        >
          <Menu className="h-6 w-6" />
        </Button>
      )}

      {/* Sidebar */}
      <div className={cn(
        "fixed inset-y-0 left-0 z-40 w-72 bg-card border-r transition-transform duration-300 transform md:relative md:translate-x-0",
        isSidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <div className="flex flex-col h-full">
          <div className="p-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-primary flex items-center gap-2">
              <div className="bg-primary/10 p-1.5 rounded-lg">
                <Bot className="h-5 w-5 text-primary" />
              </div>
              Echo AI
            </h1>
            <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setIsSidebarOpen(false)}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          <div className="px-4 mb-4">
            <Button className="w-full justify-start gap-2" variant="outline" onClick={handleCreateThread}>
              <Plus className="h-4 w-4" />
              New Chat
            </Button>
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
                    "group flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors",
                    activeThreadId === thread.id ? "bg-primary/10 text-primary" : "hover:bg-muted"
                  )}
                >
                  <div className="flex items-center gap-3 overflow-hidden">
                    <MessageSquare className="h-4 w-4 shrink-0" />
                    <span className="truncate text-sm font-medium">{thread.title}</span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity hover:text-destructive"
                    onClick={(e) => handleDeleteThread(thread.id, e)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
              {threads.length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No conversations yet
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col h-full relative">
        {/* Header */}
        <header className="h-16 border-b flex items-center px-6 bg-background/80 backdrop-blur-md sticky top-0 z-30">
          <div className="flex items-center gap-3">
            <div className="md:hidden w-10" /> {/* Spacer for menu button */}
            <h2 className="font-semibold truncate">
              {activeThread ? activeThread.title : "Select a conversation"}
            </h2>
            {activeThread && (
              <Badge variant="secondary" className="ml-2 font-normal text-[10px] uppercase tracking-wider">
                {activeThread.messages.length} messages
              </Badge>
            )}
          </div>
        </header>

        {/* Chat Area */}
        <ScrollArea className="flex-1 p-4 md:p-6">
          <div className="max-w-3xl mx-auto space-y-6 pb-24">
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

                {activeThread?.messages.map((msg, idx) => (
                  <div key={idx} className={cn(
                    "flex w-full gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300",
                    msg.role === 'user' ? "flex-row-reverse" : "flex-row"
                  )}>
                    <div className={cn(
                      "h-8 w-8 rounded-full flex items-center justify-center shrink-0 shadow-sm",
                      msg.role === 'user' ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                    )}>
                      {msg.role === 'user' ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                    </div>
                    <Card className={cn(
                      "max-w-[85%] shadow-premium border-none",
                      msg.role === 'user' ? "bg-primary text-primary-foreground" : "bg-card"
                    )}>
                      <CardContent className="p-3 md:p-4 text-sm leading-relaxed whitespace-pre-wrap">
                        {msg.content}
                      </CardContent>
                    </Card>
                  </div>
                ))}

                {/* Streaming Assistant Message */}
                {(streamingMessage || status) && (
                  <div className="flex w-full gap-4 animate-in fade-in duration-200">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                      <Bot className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <Card className="max-w-[85%] shadow-premium border-none bg-card">
                      <CardContent className="p-3 md:p-4 text-sm leading-relaxed">
                        {status && (
                          <div className="flex items-center gap-2 text-muted-foreground italic">
                            <Spinner className="h-3 w-3" />
                            {status}
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

        {/* Input Area */}
        {activeThreadId && (
          <div className="p-4 md:p-6 bg-gradient-to-t from-background via-background to-transparent absolute bottom-0 left-0 right-0">
            <div className="max-w-3xl mx-auto">
              <div className="relative group">
                <Input
                  className="pr-12 py-6 bg-card border-none shadow-premium focus-visible:ring-primary/20 rounded-2xl"
                  placeholder="How are you feeling today?"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                  disabled={loading}
                />
                <Button 
                  size="icon" 
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-xl transition-all duration-200"
                  disabled={loading || !input.trim()}
                  onClick={handleSendMessage}
                >
                  {loading ? <Spinner className="h-4 w-4" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-[10px] text-center mt-3 text-muted-foreground">
                Echo AI is a compassionate digital buddy. Always consult professionals for serious concerns.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

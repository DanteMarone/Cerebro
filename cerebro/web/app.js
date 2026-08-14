/**
 * Cerebro v2 Front-End Application
 * Built with Preact & HTM (No build step, zero bundler)
 */

import { h, render, useState, useEffect, useRef, useCallback } from "./vendor/preact.mjs";
import htm from "./vendor/htm.mjs";

const html = htm.bind(h);

function App() {
    const [channels, setChannels] = useState([]);
    const [agents, setAgents] = useState([]);
    const [activeChannelId, setActiveChannelId] = useState("dm-dante-jarvis");
    const [messages, setMessages] = useState({});
    const [streamingDeltas, setStreamingDeltas] = useState({});
    const [thinkingDeltas, setThinkingDeltas] = useState({});
    const [connected, setConnected] = useState(false);
    const [inputText, setInputText] = useState("");
    const [sending, setSending] = useState(false);

    const streamRef = useRef(null);
    const isPinnedRef = useRef(true);
    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);

    // Fetch initial channels and agents
    useEffect(() => {
        async function loadInitialData() {
            try {
                const [channelsRes, agentsRes] = await Promise.all([
                    fetch("/api/channels"),
                    fetch("/api/agents")
                ]);
                if (channelsRes.ok && agentsRes.ok) {
                    const channelsData = await channelsRes.json();
                    const agentsData = await agentsRes.json();
                    setChannels(channelsData.channels || []);
                    setAgents(agentsData.agents || []);
                    if (channelsData.channels?.length > 0) {
                        const hasDm = channelsData.channels.some(c => c.id === "dm-dante-jarvis");
                        if (!hasDm) {
                            setActiveChannelId(channelsData.channels[0].id);
                        }
                    }
                }
            } catch (err) {
                console.error("Failed to load initial data:", err);
            }
        }
        loadInitialData();
    }, []);

    // Load message history when active channel changes
    const loadChannelMessages = useCallback(async (channelId, afterId = null) => {
        if (!channelId) return;
        try {
            const url = afterId 
                ? `/api/channels/${channelId}/messages?after=${afterId}`
                : `/api/channels/${channelId}/messages`;
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                setMessages(prev => {
                    const existing = prev[channelId] || [];
                    if (afterId) {
                        const existingIds = new Set(existing.map(m => m.id));
                        const brandNew = (data.messages || []).filter(m => !existingIds.has(m.id));
                        return { ...prev, [channelId]: [...existing, ...brandNew] };
                    } else {
                        return { ...prev, [channelId]: data.messages || [] };
                    }
                });
            }
        } catch (err) {
            console.error(`Failed to load messages for ${channelId}:`, err);
        }
    }, []);

    useEffect(() => {
        loadChannelMessages(activeChannelId);
    }, [activeChannelId, loadChannelMessages]);

    // WebSocket connection and event handling
    useEffect(() => {
        let isCancelled = false;

        function connectWs() {
            if (isCancelled) return;
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${protocol}//${location.host}/ws`;
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                if (isCancelled) return;
                setConnected(true);
                // Resync active channel messages on reconnect
                setMessages(prev => {
                    const currentList = prev[activeChannelId] || [];
                    const lastId = currentList.length > 0 ? currentList[currentList.length - 1].id : null;
                    if (lastId) {
                        loadChannelMessages(activeChannelId, lastId);
                    }
                    return prev;
                });
            };

            ws.onmessage = (event) => {
                try {
                    const envelope = JSON.parse(event.data);
                    const type = envelope.type;
                    const payload = envelope.payload || {};

                    if (type === "message.new") {
                        const msg = payload.message;
                        const channelId = payload.channel_id;
                        if (msg && channelId) {
                            setMessages(prev => {
                                const list = prev[channelId] || [];
                                if (list.some(m => m.id === msg.id)) return prev;
                                return { ...prev, [channelId]: [...list, msg] };
                            });
                        }
                    } else if (type === "agent.thinking") {
                        const { message_id, text } = payload;
                        if (message_id != null && text) {
                            setThinkingDeltas(prev => ({
                                ...prev,
                                [message_id]: (prev[message_id] || "") + text
                            }));
                        }
                    } else if (type === "message.delta") {
                        const { message_id, text } = payload;
                        if (message_id != null && text) {
                            setStreamingDeltas(prev => ({
                                ...prev,
                                [message_id]: (prev[message_id] || "") + text
                            }));
                        }
                    } else if (type === "message.done") {
                        const msg = payload;
                        if (msg && msg.id != null) {
                            const channelId = msg.channel_id;
                            setStreamingDeltas(prev => {
                                const next = { ...prev };
                                delete next[msg.id];
                                return next;
                            });
                            setThinkingDeltas(prev => {
                                const next = { ...prev };
                                delete next[msg.id];
                                return next;
                            });
                            if (channelId) {
                                setMessages(prev => {
                                    const list = prev[channelId] || [];
                                    const idx = list.findIndex(m => m.id === msg.id);
                                    if (idx >= 0) {
                                        const updated = [...list];
                                        updated[idx] = msg;
                                        return { ...prev, [channelId]: updated };
                                    } else {
                                        return { ...prev, [channelId]: [...list, msg] };
                                    }
                                });
                            }
                        }
                    }
                } catch (err) {
                    console.debug("Failed to parse WS message:", err);
                }
            };

            ws.onclose = () => {
                if (isCancelled) return;
                setConnected(false);
                reconnectTimerRef.current = setTimeout(connectWs, 2000);
            };

            ws.onerror = () => {
                ws.close();
            };
        }

        connectWs();

        return () => {
            isCancelled = true;
            if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
            if (wsRef.current) wsRef.current.close();
        };
    }, [activeChannelId, loadChannelMessages]);

    // Handle scroll pinning
    const handleScroll = () => {
        if (!streamRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = streamRef.current;
        isPinnedRef.current = scrollHeight - scrollTop - clientHeight < 60;
    };

    useEffect(() => {
        if (isPinnedRef.current && streamRef.current) {
            streamRef.current.scrollTop = streamRef.current.scrollHeight;
        }
    }, [messages, streamingDeltas, activeChannelId]);

    // Send Message
    const handleSendMessage = async () => {
        const text = inputText.trim();
        if (!text || sending || !activeChannelId) return;

        setSending(true);
        try {
            const res = await fetch(`/api/channels/${activeChannelId}/messages`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    content: text,
                    author_id: "dante",
                    type: "text"
                })
            });

            if (res.ok) {
                setInputText("");
                const newMsg = await res.json();
                setMessages(prev => {
                    const list = prev[activeChannelId] || [];
                    if (list.some(m => m.id === newMsg.id)) return prev;
                    return { ...prev, [activeChannelId]: [...list, newMsg] };
                });
            }
        } catch (err) {
            console.error("Failed to send message:", err);
        } finally {
            setSending(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    };

    const activeChannel = channels.find(c => c.id === activeChannelId) || {
        id: activeChannelId,
        name: activeChannelId,
        topic: ""
    };

    const currentMessages = messages[activeChannelId] || [];

    return html`
        <div id="app">
            <!-- Sidebar -->
            <aside class="sidebar">
                <div class="sidebar-header">
                    <h1>⚡ Cerebro</h1>
                    <div class="status-badge">
                        <span class="status-dot ${connected ? 'online' : ''}"></span>
                        <span>${connected ? 'live' : 'offline'}</span>
                    </div>
                </div>

                <div class="sidebar-content">
                    <!-- Direct Messages -->
                    <div class="sidebar-section">
                        <div class="sidebar-section-title">Direct Messages</div>
                        ${channels.filter(c => c.type === 'dm').map(ch => html`
                            <div 
                                key=${ch.id} 
                                class="nav-item ${ch.id === activeChannelId ? 'active' : ''}"
                                onClick=${() => setActiveChannelId(ch.id)}
                            >
                                <span class="nav-icon">👤</span>
                                <span>${ch.name}</span>
                            </div>
                        `)}
                    </div>

                    <!-- Channels -->
                    <div class="sidebar-section">
                        <div class="sidebar-section-title">Channels</div>
                        ${channels.filter(c => c.type !== 'dm').map(ch => html`
                            <div 
                                key=${ch.id} 
                                class="nav-item ${ch.id === activeChannelId ? 'active' : ''}"
                                onClick=${() => setActiveChannelId(ch.id)}
                            >
                                <span class="nav-icon">#</span>
                                <span>${ch.name}</span>
                            </div>
                        `)}
                    </div>

                    <!-- Agents Roster -->
                    <div class="sidebar-section">
                        <div class="sidebar-section-title">Agents (${agents.length})</div>
                        ${agents.map(ag => html`
                            <div key=${ag.id} class="nav-item" style="cursor: default; opacity: 0.9;">
                                <span class="nav-icon">${ag.avatar || '🤖'}</span>
                                <span>${ag.display_name || ag.name}</span>
                            </div>
                        `)}
                    </div>
                </div>
            </aside>

            <!-- Main Chat View -->
            <main class="chat-container">
                <header class="chat-header">
                    <div class="chat-header-title">
                        <span>${activeChannel.type === 'dm' ? '👤 @' : '#'}${activeChannel.name}</span>
                        ${activeChannel.topic && html`
                            <span class="chat-header-topic">— ${activeChannel.topic}</span>
                        `}
                    </div>
                </header>

                <div class="message-stream" ref=${streamRef} onScroll=${handleScroll}>
                    ${currentMessages.length === 0 && html`
                        <div style="text-align: center; color: var(--text-secondary); margin-top: 3rem;">
                            <p style="font-size: 1.1rem; font-weight: 500;">Welcome to #${activeChannel.name}</p>
                            <p style="font-size: 0.85rem; margin-top: 0.3rem;">Start the conversation below.</p>
                        </div>
                    `}

                    ${currentMessages.map(msg => {
                        const isUser = msg.author_id === 'dante';
                        const delta = streamingDeltas[msg.id];
                        const thinking = thinkingDeltas[msg.id];
                        const content = delta ? (msg.content + delta) : msg.content;
                        const timeStr = msg.created_at ? msg.created_at.slice(11, 16) : '';

                        return html`
                            <div key=${msg.id} class="message-row">
                                <div class="message-avatar ${isUser ? 'user' : ''}">
                                    ${isUser ? 'D' : (msg.author_id?.[0]?.toUpperCase() || 'J')}
                                </div>
                                <div class="message-body">
                                    <div class="message-meta">
                                        <span class="message-author">${isUser ? 'Dante' : msg.author_id}</span>
                                        <span class="message-time">${timeStr}</span>
                                    </div>
                                    ${thinking && html`
                                        <div class="thinking-block">
                                            <div class="thinking-header">💭 Thinking...</div>
                                            <div class="thinking-content">${thinking}</div>
                                        </div>
                                    `}
                                    <div class="message-content">
                                        ${content}
                                        ${delta && html`<span class="streaming-cursor"></span>`}
                                    </div>
                                </div>
                            </div>
                        `;
                    })}
                </div>

                <div class="composer-container">
                    <div class="composer-box">
                        <textarea 
                            class="composer-textarea" 
                            placeholder="Message ${activeChannel.type === 'dm' ? '@' : '#'}${activeChannel.name}…"
                            value=${inputText}
                            onInput=${(e) => setInputText(e.target.value)}
                            onKeyDown=${handleKeyDown}
                            disabled=${sending}
                            autofocus
                        ></textarea>
                        <div class="composer-footer">
                            <span><strong>Enter</strong> to send, <strong>Shift + Enter</strong> for new line</span>
                            <button 
                                class="send-button" 
                                onClick=${handleSendMessage}
                                disabled=${!inputText.trim() || sending}
                            >
                                Send
                            </button>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    `;
}

render(html`<${App} />`, document.body);

/**
 * Cerebro v2 Front-End Application
 * Built with pure Preact Hyperscript (Zero-build, zero parser overhead, 100% reliable)
 */

import { h, render } from "./vendor/preact.module.js";
import { useState, useEffect, useRef, useCallback } from "./vendor/hooks.module.js";

function formatTokens(n) {
    if (n === null || n === undefined) return "-";
    if (n < 1000) return String(n);
    if (n < 1000000) return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k`;
    return `${(n / 1000000).toFixed(1)}M`;
}

function formatAge(seconds) {
    if (seconds === null || seconds === undefined) return "age unknown";
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function App() {
    const [channels, setChannels] = useState([]);
    const [agents, setAgents] = useState([]);
    const [activeChannelId, setActiveChannelId] = useState("warroom");
    const [channelMembers, setChannelMembers] = useState([]);
    const [messages, setMessages] = useState({});
    const [streamingDeltas, setStreamingDeltas] = useState({});
    const [thinkingDeltas, setThinkingDeltas] = useState({});
    const [drafts, setDrafts] = useState({});
    const [unreadCounts, setUnreadCounts] = useState({});
    const [activeTurns, setActiveTurns] = useState({});
    const [connected, setConnected] = useState(false);
    const [sending, setSending] = useState(false);
    const [isPinned, setIsPinned] = useState(true);

    // Modal states
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showDmModal, setShowDmModal] = useState(false);
    const [showAddMemberModal, setShowAddMemberModal] = useState(false);

    // Channel creation state
    const [newChanName, setNewChanName] = useState("");
    const [newChanTopic, setNewChanTopic] = useState("");
    const [selectedAgents, setSelectedAgents] = useState([]);
    const [creatingChannel, setCreatingChannel] = useState(false);

    // Member addition state
    const [addingMember, setAddingMember] = useState(false);

    // Leases state (§8.7)
    const [leases, setLeases] = useState([]);

    // Usage board state (§13.2)
    const [usage, setUsage] = useState({ agents: [] });

    // Deployment freshness: is this server running the code that is on disk?
    const [health, setHealth] = useState(null);

    // Transient silence/pass notices for group channels (§9.3)
    const [passedNotices, setPassedNotices] = useState({});

    const streamRef = useRef(null);
    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const activeChannelIdRef = useRef(activeChannelId);

    useEffect(() => {
        activeChannelIdRef.current = activeChannelId;
    }, [activeChannelId]);

    const currentDraft = drafts[activeChannelId] || "";

    // Fetch initial channels and agents
    const loadChannelsAndAgents = useCallback(async () => {
        try {
            const [channelsRes, agentsRes] = await Promise.all([
                fetch("/api/channels"),
                fetch("/api/agents")
            ]);
            if (channelsRes.ok && agentsRes.ok) {
                const channelsData = await channelsRes.json();
                const agentsData = await agentsRes.json();
                const chList = channelsData.channels || [];
                setChannels(chList);
                setAgents(agentsData.agents || []);

                const serverUnreads = {};
                chList.forEach(ch => {
                    if (ch.id !== activeChannelIdRef.current) {
                        serverUnreads[ch.id] = ch.unread_count || 0;
                    } else {
                        serverUnreads[ch.id] = 0;
                    }
                });
                setUnreadCounts(prev => ({ ...serverUnreads, ...prev }));

                if (chList.length > 0 && !chList.some(c => c.id === activeChannelId)) {
                    const warRoom = chList.find(c => c.id === "warroom");
                    setActiveChannelId(warRoom ? "warroom" : chList[0].id);
                }
            }
        } catch (err) {
            console.error("Failed to load initial data:", err);
        }
    }, [activeChannelId]);

    // Fetch active distributed mutex leases (§8.7)
    const loadLeases = useCallback(async () => {
        try {
            const res = await fetch("/api/leases");
            if (res.ok) {
                const data = await res.json();
                setLeases(data.leases || []);
            }
        } catch (err) {
            console.debug("Failed to load leases:", err);
        }
    }, []);

    // Fetch the usage board (§13.2)
    const loadUsage = useCallback(async () => {
        try {
            const res = await fetch("/api/usage");
            if (res.ok) {
                setUsage(await res.json());
            }
        } catch (err) {
            console.debug("Failed to load usage:", err);
        }
    }, []);

    useEffect(() => {
        loadUsage();
        const timer = setInterval(loadUsage, 30000);
        return () => clearInterval(timer);
    }, [loadUsage]);

    // Staleness is only useful if it is noticed. Three fixes once sat landed-but-not-running for
    // half an hour while the room read as though they had shipped.
    const loadHealth = useCallback(async () => {
        try {
            const res = await fetch("/api/health");
            if (res.ok) setHealth(await res.json());
        } catch (err) {
            console.debug("Failed to load health:", err);
        }
    }, []);

    useEffect(() => {
        loadHealth();
        const timer = setInterval(loadHealth, 30000);
        return () => clearInterval(timer);
    }, [loadHealth]);

    useEffect(() => {
        loadChannelsAndAgents();
        loadLeases();
    }, [loadChannelsAndAgents, loadLeases]);

    // Fetch members for the active channel
    const loadActiveMembers = useCallback(async (channelId) => {
        if (!channelId) return;
        try {
            const res = await fetch(`/api/channels/${channelId}/members`);
            if (res.ok) {
                const data = await res.json();
                setChannelMembers(data.members || []);
            }
        } catch (err) {
            console.error(`Failed to load members for ${channelId}:`, err);
        }
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

    // Advance read cursor on the server
    const markChannelRead = useCallback(async (channelId, maxMessageId) => {
        if (!channelId || maxMessageId == null) return;
        try {
            await fetch(`/api/channels/${channelId}/read`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message_id: maxMessageId })
            });
        } catch (err) {
            console.debug("Failed to update read cursor:", err);
        }
    }, []);

    // Channel selection handler: resets unread count and marks read on server
    const selectChannel = (channelId) => {
        setActiveChannelId(channelId);
        setUnreadCounts(prev => ({ ...prev, [channelId]: 0 }));
        const list = messages[channelId] || [];
        if (list.length > 0) {
            const maxId = Math.max(...list.map(m => m.id));
            markChannelRead(channelId, maxId);
        }
    };

    useEffect(() => {
        loadChannelMessages(activeChannelId);
        loadActiveMembers(activeChannelId);
        setIsPinned(true);
        if (streamRef.current) {
            setTimeout(() => {
                if (streamRef.current) {
                    streamRef.current.scrollTop = streamRef.current.scrollHeight;
                }
            }, 50);
        }
    }, [activeChannelId, loadChannelMessages, loadActiveMembers]);

    // Mark active channel messages as read whenever messages update
    useEffect(() => {
        const list = messages[activeChannelId] || [];
        if (list.length > 0) {
            const maxId = Math.max(...list.map(m => m.id));
            markChannelRead(activeChannelId, maxId);
        }
    }, [activeChannelId, messages, markChannelRead]);

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

                            // Clear active turn indicator by turn_id
                            const turnId = msg.turn_id;
                            if (turnId) {
                                setActiveTurns(prev => {
                                    const ch = { ...(prev[channelId] || {}) };
                                    delete ch[turnId];
                                    return { ...prev, [channelId]: ch };
                                });
                            }

                            // Increment unread count if message is on an inactive channel
                            if (channelId !== activeChannelIdRef.current) {
                                setUnreadCounts(prev => ({
                                    ...prev,
                                    [channelId]: (prev[channelId] || 0) + 1
                                }));
                            }
                        }
                    } else if (type === "agent.status" || type === "agent.activity") {
                        const { channel_id, agent_id, turn_id, status } = payload;
                        if (channel_id && turn_id) {
                            if (status === "thinking" || (status && status.startsWith("tool:"))) {
                                setActiveTurns(prev => ({
                                    ...prev,
                                    [channel_id]: {
                                        ...(prev[channel_id] || {}),
                                        [turn_id]: { turn_id, agent_id, status }
                                    }
                                }));
                            } else if (status === "idle" || status === "cancelled") {
                                setActiveTurns(prev => {
                                    const ch = { ...(prev[channel_id] || {}) };
                                    delete ch[turn_id];
                                    return { ...prev, [channel_id]: ch };
                                });
                            }
                        }
                    } else if (type === "turn.cancelled" || type === "turn.discarded") {
                        const { channel_id, turn_id, agent_id } = payload;
                        if (channel_id && turn_id) {
                            setActiveTurns(prev => {
                                const ch = { ...(prev[channel_id] || {}) };
                                delete ch[turn_id];
                                return { ...prev, [channel_id]: ch };
                            });
                        }
                        if (type === "turn.discarded" && channel_id && !channel_id.startsWith("dm-")) {
                            const noticeId = `${turn_id || Date.now()}-${agent_id || "agent"}`;
                            const notice = {
                                id: noticeId,
                                agent_id: agent_id || "agent",
                                text: `@${agent_id || "agent"} considered this and passed`,
                                at: Date.now()
                            };
                            setPassedNotices(prev => ({
                                ...prev,
                                [channel_id]: [...(prev[channel_id] || []).filter(n => Date.now() - n.at < 4000), notice]
                            }));
                            setTimeout(() => {
                                setPassedNotices(prev => ({
                                    ...prev,
                                    [channel_id]: (prev[channel_id] || []).filter(n => n.id !== noticeId)
                                }));
                            }, 4000);
                        }
                    } else if (type === "error") {
                        const { channel_id, turn_id } = payload;
                        if (channel_id && turn_id) {
                            setActiveTurns(prev => {
                                const ch = { ...(prev[channel_id] || {}) };
                                delete ch[turn_id];
                                return { ...prev, [channel_id]: ch };
                            });
                        }
                    } else if (type === "lease.acquired" || type === "lease.released" || type === "lease.expired") {
                        loadLeases();
                    } else if (type === "agent.thinking") {
                        const { message_id, text } = payload;
                        if (message_id != null && text) {
                            setThinkingDeltas(prev => ({
                                ...prev,
                                [message_id]: (prev[message_id] || "") + text
                            }));
                        }
                    } else if (type === "message.done") {
                        const msg = payload.message || payload;
                        if (msg && msg.id != null) {
                            const channelId = msg.channel_id;
                            const turnId = msg.turn_id;
                            if (turnId && channelId) {
                                setActiveTurns(prev => {
                                    const ch = { ...(prev[channelId] || {}) };
                                    delete ch[turnId];
                                    return { ...prev, [channelId]: ch };
                                });
                            }
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
                    } else if (type === "channel.new" || type === "channel.update") {
                        loadChannelsAndAgents();
                        if (payload.channel && payload.channel.id === activeChannelIdRef.current) {
                            loadActiveMembers(activeChannelIdRef.current);
                        }
                    } else if (type === "channel.read") {
                        const { channel_id, member_id } = payload;
                        if (member_id === "dante" && channel_id === activeChannelIdRef.current) {
                            setUnreadCounts(prev => ({ ...prev, [channel_id]: 0 }));
                        }
                    }
                } catch (err) {
                    console.debug("Failed to parse WS message:", err);
                }
            };

            ws.onclose = () => {
                if (isCancelled) return;
                setConnected(false);
                setActiveTurns({});
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
    }, [activeChannelId, loadChannelMessages, loadChannelsAndAgents, loadActiveMembers]);

    const handleScroll = () => {
        if (!streamRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = streamRef.current;
        const pinned = scrollHeight - scrollTop - clientHeight < 60;
        setIsPinned(pinned);
    };

    useEffect(() => {
        if (isPinned && streamRef.current) {
            streamRef.current.scrollTop = streamRef.current.scrollHeight;
        }
    }, [messages, streamingDeltas, thinkingDeltas, isPinned]);

    const handleSendMessage = async () => {
        const text = currentDraft.trim();
        if (!text || sending || !activeChannelId) return;

        setSending(true);
        try {
            const res = await fetch(`/api/channels/${activeChannelId}/messages`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    content: text,
                    author_id: "dante",
                    type: "chat"
                })
            });

            if (res.ok) {
                setDrafts(prev => ({ ...prev, [activeChannelId]: "" }));
                const newMsg = await res.json();
                setMessages(prev => {
                    const list = prev[activeChannelId] || [];
                    if (list.some(m => m.id === newMsg.id)) return prev;
                    return { ...prev, [activeChannelId]: [...list, newMsg] };
                });
                setIsPinned(true);
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

    const handleCreateChannel = async (e) => {
        e.preventDefault();
        const name = newChanName.trim();
        if (!name || creatingChannel) return;

        setCreatingChannel(true);
        try {
            const res = await fetch("/api/channels", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: name,
                    topic: newChanTopic.trim(),
                    member_ids: selectedAgents,
                    kind: "topic"
                })
            });

            if (res.ok) {
                const data = await res.json();
                const created = data.channel;
                await loadChannelsAndAgents();
                setShowCreateModal(false);
                setNewChanName("");
                setNewChanTopic("");
                setSelectedAgents([]);
                if (created && created.id) {
                    selectChannel(created.id);
                }
            } else {
                const err = await res.json();
                alert(err.detail || "Failed to create channel");
            }
        } catch (err) {
            console.error("Channel creation error:", err);
            alert("Error creating channel");
        } finally {
            setCreatingChannel(false);
        }
    };

    const handleStartDm = async (agent) => {
        const dmChannelId = `dm-dante-${agent.id}`;
        const existing = channels.find(c => c.id === dmChannelId);
        if (existing) {
            selectChannel(dmChannelId);
            setShowDmModal(false);
            return;
        }

        try {
            const res = await fetch("/api/channels", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: agent.display_name || agent.name,
                    id: dmChannelId,
                    kind: "dm",
                    topic: `Direct Message with ${agent.display_name || agent.name}`,
                    member_ids: [agent.id]
                })
            });

            if (res.ok) {
                await loadChannelsAndAgents();
                selectChannel(dmChannelId);
                setShowDmModal(false);
            } else {
                const err = await res.json();
                alert(err.detail || "Failed to start Direct Message");
            }
        } catch (err) {
            console.error("Failed to start DM:", err);
            alert("Error starting Direct Message");
        }
    };

    const handleAddMember = async (agentId) => {
        if (!activeChannelId || addingMember) return;
        setAddingMember(true);
        try {
            const res = await fetch(`/api/channels/${activeChannelId}/members`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    member_id: agentId,
                    member_kind: "agent",
                    listen_mode: "auto"
                })
            });

            if (res.ok) {
                await loadActiveMembers(activeChannelId);
                setShowAddMemberModal(false);
            } else {
                const err = await res.json();
                alert(err.detail || "Failed to add member to channel");
            }
        } catch (err) {
            console.error("Failed to add member:", err);
            alert("Error adding member");
        } finally {
            setAddingMember(false);
        }
    };

    const toggleAgentSelection = (agentId) => {
        setSelectedAgents(prev => 
            prev.includes(agentId) ? prev.filter(id => id !== agentId) : [...prev, agentId]
        );
    };

    const activeChannel = channels.find(c => c.id === activeChannelId) || {
        id: activeChannelId,
        name: activeChannelId,
        topic: ""
    };

    const currentMessages = messages[activeChannelId] || [];
    const nonMemberAgents = agents.filter(ag => !channelMembers.some(m => m.member_id === ag.id));

    return h("div", { class: "app-container" }, [
        // Deployment banner. Rendered only when the server can actually tell -- an unknown commit
        // says nothing rather than guessing, because a false "up to date" is worse than silence.
        health && health.stale
            ? h("div", { class: "stale-banner", "data-stale-banner": "true" }, [
                h("strong", null, "This server is running older code than the repository."),
                h("span", { class: "stale-detail" },
                    ` running ${health.running_commit} · repo at ${health.repo_commit}`),
                h("span", { class: "stale-hint" }, "Restart with scripts/deploy.py to pick it up."),
              ])
            : null,

        h("div", { class: "app-layout" }, [
            // Sidebar
            h("aside", { class: "sidebar" }, [
            h("div", { class: "sidebar-header" }, [
                h("h1", null, "⚡ Cerebro"),
                h("div", { class: "status-badge" }, [
                    h("span", { class: `status-dot ${connected ? 'online' : ''}` }),
                    h("span", null, connected ? 'live' : 'offline'),
                ]),
            ]),
            h("div", { class: "sidebar-content" }, [
                // Direct Messages (with + button)
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, "Direct Messages"),
                        h("button", {
                            class: "section-add-btn",
                            title: "New Direct Message",
                            onClick: () => setShowDmModal(true)
                        }, "+")
                    ]),
                    ...channels.filter(c => c.type === 'dm' || c.kind === 'dm').map(ch => {
                        const unread = unreadCounts[ch.id] || 0;
                        return h("div", {
                            key: ch.id,
                            class: `nav-item ${ch.id === activeChannelId ? 'active' : ''}`,
                            onClick: () => selectChannel(ch.id)
                        }, [
                            h("span", { class: "nav-icon" }, "👤"),
                            h("span", null, ch.name),
                            unread > 0 ? h("span", { class: "unread-badge" }, unread) : null
                        ]);
                    })
                ]),

                // Channels (with + button)
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, "Channels"),
                        h("button", {
                            class: "section-add-btn",
                            title: "Create Channel",
                            onClick: () => setShowCreateModal(true)
                        }, "+")
                    ]),
                    ...channels.filter(c => c.type !== 'dm' && c.kind !== 'dm').map(ch => {
                        const unread = unreadCounts[ch.id] || 0;
                        return h("div", {
                            key: ch.id,
                            class: `nav-item ${ch.id === activeChannelId ? 'active' : ''}`,
                            onClick: () => selectChannel(ch.id)
                        }, [
                            h("span", { class: "nav-icon" }, "#"),
                            h("span", null, ch.name),
                            unread > 0 ? h("span", { class: "unread-badge" }, unread) : null
                        ]);
                    })
                ]),

                // Agent Roster
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, `Agents (${agents.length})`)
                    ]),
                    ...agents.map(ag =>
                        h("div", {
                            key: ag.id,
                            class: "nav-item",
                            title: `Start DM with ${ag.display_name || ag.name}`,
                            onClick: () => handleStartDm(ag)
                        }, [
                            h("span", { class: "nav-icon" }, ag.avatar || "🤖"),
                            h("span", null, ag.display_name || ag.name)
                        ])
                    )
                ]),

                // Active Leases Section (§8.7)
                h("div", { class: "sidebar-section leases-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, `Active Leases (${leases.length})`)
                    ]),
                    leases.length === 0
                        ? h("div", { class: "nav-item-empty", style: "padding: 4px 12px; font-size: 11px; color: var(--text-muted);" }, "No active locks")
                        : leases.map(l =>
                            h("div", {
                                key: l.resource,
                                class: "nav-item lease-item",
                                "data-lease-resource": l.resource,
                                title: `${l.resource}\nHeld by: @${l.holder_id}\nExpires: ${l.expires_at}\nReason: ${l.reason || 'None'}`
                            }, [
                                h("span", { class: "nav-icon" }, "🔒"),
                                h("span", { class: "lease-resource-label", style: "font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" }, l.resource),
                                h("span", { class: "lease-holder-pill", style: "margin-left: auto; font-size: 10px; opacity: 0.8;" }, `@${l.holder_id}`)
                            ])
                        )
                ]),

                // Usage & Quota Board (§13.2)
                //
                // Measured tokens and self-reported windows are rendered as visibly different
                // things. They are not commensurable: one is something Cerebro observed, the other
                // is an agent's word about a meter Cerebro cannot see. A stale self-report says so
                // rather than sitting next to a measured number looking equally solid.
                h("div", { class: "sidebar-section usage-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, `Usage (${usage.agents ? usage.agents.length : 0})`)
                    ]),
                    (!usage.agents || usage.agents.length === 0)
                        ? h("div", { class: "nav-item-empty", style: "padding: 4px 12px; font-size: 11px; color: var(--text-muted);" }, "Nothing reported yet")
                        : usage.agents.map(a =>
                            h("div", {
                                key: a.agent_id,
                                class: "usage-item",
                                "data-usage-agent": a.agent_id
                            }, [
                                h("div", { class: "usage-agent-row" }, [
                                    h("span", { class: "usage-agent-name" }, `@${a.agent_id}`),
                                    a.measured
                                        ? h("span", {
                                            class: "usage-measured",
                                            title: `${a.measured.calls} calls, ${a.measured.input_tokens} in / ${a.measured.output_tokens} out (measured by Cerebro)`
                                          }, `${formatTokens(a.measured.total_tokens)} tok`)
                                        : h("span", { class: "usage-unmeasured", title: "Cerebro does not call this agent's provider, so it cannot measure its tokens" }, "not measured")
                                ]),
                                ...(a.windows || []).map(w =>
                                    h("div", {
                                        key: w.window,
                                        class: `usage-window${w.stale ? " is-stale" : ""}`,
                                        "data-usage-window": w.window,
                                        "data-stale": w.stale ? "true" : "false",
                                        title: `Self-reported by @${w.reported_by}${w.relayed ? " (relayed)" : ""} at ${w.reported_at}${w.note ? " — " + w.note : ""}`
                                    }, [
                                        h("span", { class: "usage-window-name" }, w.window),
                                        h("span", { class: "usage-window-value" },
                                            w.pct_remaining === null || w.pct_remaining === undefined
                                                ? "unknown"
                                                : `${Math.round(w.pct_remaining)}% left`),
                                        h("span", { class: "usage-window-age" },
                                            w.stale ? `stale · ${formatAge(w.age_seconds)}` : formatAge(w.age_seconds)),
                                        w.relayed ? h("span", { class: "usage-relayed", title: `Relayed by @${w.reported_by}` }, "relayed") : null
                                    ])
                                )
                            ])
                        )
                ])
            ])
        ]),

        // Main Chat Area
        h("main", { class: "chat-container", style: "position: relative;" }, [
            h("header", { class: "chat-header" }, [
                h("div", { class: "chat-header-title" }, [
                    h("span", null, (activeChannel.type === 'dm' || activeChannel.kind === 'dm') ? `👤 @${activeChannel.name}` : `#${activeChannel.name}`),
                    activeChannel.topic ? h("span", { class: "chat-header-topic" }, `— ${activeChannel.topic}`) : null
                ]),
                h("div", { class: "chat-header-actions" }, [
                    channelMembers.length > 0 ? h("div", { class: "member-pill" }, [
                        h("span", null, `👥 ${channelMembers.length} members`)
                    ]) : null,
                    h("button", {
                        class: "header-action-btn",
                        title: "Add Agent to Channel",
                        onClick: () => setShowAddMemberModal(true)
                    }, "+ Add Agent")
                ])
            ]),

            // Message Stream
            h("div", { class: "message-stream", ref: streamRef, onScroll: handleScroll }, [
                currentMessages.length === 0 ? h("div", { style: "text-align: center; color: var(--text-secondary); margin-top: 3rem;" }, [
                    h("p", { style: "font-size: 1.1rem; font-weight: 500;" }, `Welcome to #${activeChannel.name}`),
                    h("p", { style: "font-size: 0.85rem; margin-top: 0.3rem;" }, "Start the conversation below.")
                ]) : null,

                ...currentMessages.map(msg => {
                    const author = msg.display_author_id || msg.author_id;
                    const isUser = author === 'dante';
                    const delta = streamingDeltas[msg.id];
                    const thinking = thinkingDeltas[msg.id];
                    const base = msg.body ?? msg.content ?? '';
                    const content = delta ? (base + delta) : base;
                    const timeStr = msg.created_at ? msg.created_at.slice(11, 16) : '';

                    return h("div", { key: msg.id, class: "message-row" }, [
                        h("div", { class: `message-avatar ${isUser ? 'user' : ''}` },
                            isUser ? 'D' : (author?.[0]?.toUpperCase() || 'J')
                        ),
                        h("div", { class: "message-body" }, [
                            h("div", { class: "message-meta" }, [
                                h("span", { class: "message-author" }, isUser ? 'Dante' : author),
                                h("span", { class: "message-time" }, timeStr)
                            ]),
                            thinking ? h("div", { class: "thinking-block" }, [
                                h("div", { class: "thinking-header" }, "💭 Thinking..."),
                                h("div", { class: "thinking-content" }, thinking)
                            ]) : null,
                            h("div", { class: "message-content" }, [
                                content,
                                delta ? h("span", { class: "streaming-cursor" }) : null
                            ])
                        ])
                    ]);
                }),

                ...Object.entries(activeTurns[activeChannelId] || {}).map(([turnId, turn]) => {
                    const agent = agents.find(a => a.id === turn.agent_id) || { name: turn.agent_id, avatar: "🤖" };
                    return h("div", { key: `turn-${turnId}`, "data-turn-id": turnId, class: "message-row turn-activity-row" }, [
                        h("div", { class: "message-avatar" }, agent.avatar || (agent.name?.[0]?.toUpperCase()) || "🤖"),
                        h("div", { class: "message-body" }, [
                            h("div", { class: "message-meta" }, [
                                h("span", { class: "message-author" }, agent.display_name || agent.name || turn.agent_id),
                                h("span", { class: "message-time" }, "working...")
                            ]),
                            h("div", { class: "thinking-block active-thinking" }, [
                                h("div", { class: "thinking-header" }, [
                                    h("span", { class: "thinking-spinner" }),
                                    h("span", null, `${agent.display_name || agent.name || turn.agent_id} is reasoning...`)
                                ])
                            ])
                        ])
                    ]);
                }),

                ...(passedNotices[activeChannelId] || []).map(notice => {
                    return h("div", { key: notice.id, class: "transient-pass-notice" }, [
                        h("span", { class: "pass-icon" }, "⏭"),
                        h("span", null, notice.text)
                    ]);
                })
            ]),

            // Jump to latest button
            !isPinned ? h("button", {
                class: "jump-bottom-btn",
                onClick: () => {
                    if (streamRef.current) {
                        streamRef.current.scrollTop = streamRef.current.scrollHeight;
                        setIsPinned(true);
                    }
                }
            }, "↓ Jump to latest") : null,

            // Composer
            h("div", { class: "composer-container" }, [
                h("div", { class: "composer-box" }, [
                    h("textarea", {
                        class: "composer-textarea",
                        placeholder: `Message ${(activeChannel.type === 'dm' || activeChannel.kind === 'dm') ? '@' : '#'}${activeChannel.name}…`,
                        value: currentDraft,
                        onInput: (e) => setDrafts(prev => ({ ...prev, [activeChannelId]: e.target.value })),
                        onKeyDown: handleKeyDown,
                        disabled: sending,
                        autofocus: true
                    }),
                    h("div", { class: "composer-footer" }, [
                        h("span", null, [
                            h("strong", null, "Enter"),
                            " to send, ",
                            h("strong", null, "Shift + Enter"),
                            " for new line"
                        ]),
                        h("button", {
                            class: "send-button",
                            onClick: handleSendMessage,
                            disabled: !currentDraft.trim() || sending
                        }, "Send")
                    ])
                ])
            ]),
        ]),

        // New DM Modal Dialog
        showDmModal ? h("div", { class: "modal-backdrop", onClick: (e) => {
            if (e.target === e.currentTarget) setShowDmModal(false);
        }}, [
            h("div", { class: "modal-dialog" }, [
                h("div", { class: "modal-header" }, [
                    h("h2", null, "New Direct Message"),
                    h("button", { class: "modal-close-btn", onClick: () => setShowDmModal(false) }, "✕")
                ]),
                h("div", { class: "modal-body" }, [
                    h("p", { style: "font-size: 0.85rem; color: var(--text-secondary);" },
                        "Select an agent to open or start a direct message conversation:"
                    ),
                    h("div", { class: "agent-select-list" }, [
                        ...agents.map(ag => h("div", {
                            key: ag.id,
                            class: "agent-select-item",
                            onClick: () => handleStartDm(ag)
                        }, [
                            h("span", { style: "font-size: 1.5rem;" }, ag.avatar || "🤖"),
                            h("div", { class: "agent-select-info" }, [
                                h("span", { class: "agent-select-name" }, ag.display_name || ag.name),
                                h("span", { class: "agent-select-role" }, `${ag.role || 'Agent'} · ${ag.model || 'local'}`)
                            ])
                        ]))
                    ])
                ]),
                h("div", { class: "modal-footer" }, [
                    h("button", { class: "btn-secondary", onClick: () => setShowDmModal(false) }, "Close")
                ])
            ])
        ]) : null,

        // Add Member Modal Dialog
        showAddMemberModal ? h("div", { class: "modal-backdrop", onClick: (e) => {
            if (e.target === e.currentTarget) setShowAddMemberModal(false);
        }}, [
            h("div", { class: "modal-dialog" }, [
                h("div", { class: "modal-header" }, [
                    h("h2", null, `Add Agent to #${activeChannel.name}`),
                    h("button", { class: "modal-close-btn", onClick: () => setShowAddMemberModal(false) }, "✕")
                ]),
                h("div", { class: "modal-body" }, [
                    nonMemberAgents.length === 0
                        ? h("p", { style: "font-size: 0.9rem; color: var(--text-secondary); text-align: center;" },
                            "All available agents are already members of this channel."
                        )
                        : h("div", { class: "agent-select-list" }, [
                            ...nonMemberAgents.map(ag => h("div", {
                                key: ag.id,
                                class: "agent-select-item",
                                onClick: () => handleAddMember(ag.id)
                            }, [
                                h("span", { style: "font-size: 1.5rem;" }, ag.avatar || "🤖"),
                                h("div", { class: "agent-select-info" }, [
                                    h("span", { class: "agent-select-name" }, ag.display_name || ag.name),
                                    h("span", { class: "agent-select-role" }, `${ag.role || 'Agent'} · ${ag.model || 'local'}`)
                                ]),
                                h("button", {
                                    class: "btn-primary",
                                    style: "margin-left: auto; padding: 0.3rem 0.7rem; font-size: 0.8rem;",
                                    disabled: addingMember
                                }, "Add")
                            ]))
                        ])
                ]),
                h("div", { class: "modal-footer" }, [
                    h("button", { class: "btn-secondary", onClick: () => setShowAddMemberModal(false) }, "Close")
                ])
            ])
        ]) : null,

        // Create Channel Modal Dialog
        showCreateModal ? h("div", { class: "modal-backdrop", onClick: (e) => {
            if (e.target === e.currentTarget) setShowCreateModal(false);
        }}, [
            h("div", { class: "modal-dialog" }, [
                h("div", { class: "modal-header" }, [
                    h("h2", null, "Create Channel"),
                    h("button", { class: "modal-close-btn", onClick: () => setShowCreateModal(false) }, "✕")
                ]),
                h("div", { class: "modal-body" }, [
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Channel Name"),
                        h("input", {
                            class: "form-input",
                            type: "text",
                            placeholder: "e.g. general, feature-planning",
                            value: newChanName,
                            onInput: (e) => setNewChanName(e.target.value),
                            autofocus: true
                        })
                    ]),
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Topic (Optional)"),
                        h("input", {
                            class: "form-input",
                            type: "text",
                            placeholder: "What is this channel about?",
                            value: newChanTopic,
                            onInput: (e) => setNewChanTopic(e.target.value)
                        })
                    ]),
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Add Agents to Channel"),
                        h("div", { class: "agent-checkbox-grid" }, [
                            ...agents.map(ag => h("label", { key: ag.id, class: "agent-checkbox-item" }, [
                                h("input", {
                                    type: "checkbox",
                                    checked: selectedAgents.includes(ag.id),
                                    onChange: () => toggleAgentSelection(ag.id)
                                }),
                                h("span", null, `${ag.avatar || '🤖'} ${ag.name}`)
                            ]))
                        ])
                    ]),
                    h("p", { style: "font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.2rem;" },
                        "🔒 You (@dante) are automatically enrolled as the channel owner."
                    )
                ]),
                h("div", { class: "modal-footer" }, [
                    h("button", { class: "btn-secondary", onClick: () => setShowCreateModal(false) }, "Cancel"),
                    h("button", {
                        class: "btn-primary",
                        disabled: !newChanName.trim() || creatingChannel,
                        onClick: handleCreateChannel
                    }, creatingChannel ? "Creating..." : "Create Channel")
                ])
            ])
        ]) : null
    ]);
}

const mountTarget = document.getElementById("app") || document.body;
render(h(App, null), mountTarget);

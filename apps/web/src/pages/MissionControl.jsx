import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { fetchMissions, launchMission } from '../services/api';

export default function MissionControl() {
    const [goal, setGoal] = useState('');
    const [loading, setLoading] = useState(false);
    const [missions, setMissions] = useState([]);
    const [activeMission, setActiveMission] = useState(null);
    
    // Live stream states
    const [liveLogs, setLiveLogs] = useState([]);
    const [currentMissionId, setCurrentMissionId] = useState(null);
    const currentMissionIdRef = useRef(null);
    const consoleEndRef = useRef(null);
    const socketRef = useRef(null);

    // Initialize Socket Connection and History Catalogs
    useEffect(() => {
        loadHistory();

        // Connect to the Express live websocket gateway
        socketRef.current = io('http://localhost:5001');

        // Intercept line-by-line step execution frames from the server
        socketRef.current.on('mission-step', (streamFrame) => {
            if (streamFrame.missionId === currentMissionIdRef.current) {
                setLiveLogs((prevLogs) => [...prevLogs, streamFrame.log]);
            }
        });

        socketRef.current.on('mission-complete', (finalFrame) => {
            if (finalFrame.missionId !== currentMissionIdRef.current) return;

            setLiveLogs((prev) => [...prev, `[System]: Mission ${finalFrame.status.toUpperCase()}${finalFrame.error ? ` - ${finalFrame.error}` : ''}`]);

            if (finalFrame.status === 'completed') {
                setActiveMission((prev) => ({ ...prev, status: 'completed', data: finalFrame.data }));
            } else {
                setActiveMission((prev) => ({ ...prev, status: 'failed', error: finalFrame.error }));
            }
            setLoading(false);
            loadHistory();
        });

        return () => {
            if (socketRef.current) socketRef.current.disconnect();
        };
    }, []);

    // Auto-scroll terminal interface down as new logs arrive
    useEffect(() => {
        if (consoleEndRef.current) {
            consoleEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [liveLogs]);

    const loadHistory = async () => {
        try {
            const data = await fetchMissions();
            setMissions(data.missions || []);
        } catch (err) {
            console.error("Failed to load historical logs:", err);
        }
    };

    const getActiveAnswer = () => {
        if (!activeMission?.data) return null;
        if (typeof activeMission.data === 'string') return activeMission.data;
        if (activeMission.data.weather) return activeMission.data.weather;
        if (activeMission.data.message) return activeMission.data.message;
        if (activeMission.data.workflow === 'gem_tender_discovery') {
            const count = activeMission.data.opportunities?.length || 0;
            const filters = activeMission.data.filters || {};
            const status = activeMission.data.status === 'needs_operator_review' ? 'Needs operator review' : 'Completed';
            return [
                `${status}: ${count} public tender opportunities extracted.`,
                `Category: ${filters.category || 'Not specified'}`,
                `State: ${filters.state || 'All India'}`,
                filters.max_value_inr ? `Budget ceiling: INR ${filters.max_value_inr}` : null,
                activeMission.data.official_gem_bids_url ? `Official GeM bids page: ${activeMission.data.official_gem_bids_url}` : null,
                activeMission.data.note || null
            ].filter(Boolean).join('\n');
        }
        if (activeMission.data.workflow === 'gst_assistant' || activeMission.data.workflow === 'udyam_assistant') {
            return activeMission.data.summary || JSON.stringify(activeMission.data, null, 2);
        }
        return JSON.stringify(activeMission.data, null, 2);
    };

    const handleLaunch = async (e) => {
        e.preventDefault();
        if (!goal.trim()) return;

        setLoading(true);
        setLiveLogs(["[System]: Priming cloud environment hooks...", "[System]: Spawning sandboxed agent engine thread..."]);

        try {
            const response = await launchMission(goal);
            if (response.success) {
                setActiveMission({ goal, missionId: response.missionId, status: response.status, data: null });
                setCurrentMissionId(response.missionId);
                currentMissionIdRef.current = response.missionId;
                setGoal('');
            } else {
                setActiveMission({ goal, status: 'failed', error: response.error });
                setLoading(false);
            }
        } catch (err) {
            console.error("Execution failed:", err);
            setActiveMission({ goal, status: 'failed', error: err.message });
            setLoading(false);
        }
    };

    return (
        <div style={{ display: 'flex', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto', height: '100vh', margin: 0, backgroundColor: '#0f172a', color: '#f8fafc' }}>
            
            {/* Sidebar Controls (Left Panel) */}
            <div style={{ width: '320px', backgroundColor: '#1e293b', padding: '24px', borderRight: '1px solid #334155', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                <h3 style={{ margin: '0 0 16px 0', color: '#38bdf8', fontSize: '18px', fontWeight: '600' }}>Mission Run Logs</h3>
                <hr style={{ border: 'none', borderTop: '1px solid #334155', marginBottom: '20px' }} />
                
                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {missions.length === 0 ? (
                        <p style={{ color: '#94a3b8', fontSize: '14px' }}>No historical tasks stored in Atlas cluster.</p>
                    ) : (
                        missions.map((m) => (
                            <div key={m._id} style={{ padding: '12px', margin: '0 0 12px 0', borderRadius: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', transition: 'all 0.2s' }}>
                                <div style={{ fontWeight: '500', fontSize: '13px', color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.goal}</div>
                                <div style={{ fontSize: '11px', marginTop: '6px', display: 'inline-block', padding: '2px 8px', borderRadius: '4px', fontWeight: '600', backgroundColor: m.status === 'completed' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)', color: m.status === 'completed' ? '#4ade80' : '#f87171' }}>
                                    {m.status.toUpperCase()}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Main Interactive Execution Area (Right Panel) */}
            <div style={{ flex: 1, padding: '40px', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <h2 style={{ margin: 0, fontSize: '28px', fontWeight: '700', letterSpacing: 0 }}>KaryaAI Core Operator</h2>
                    <span style={{ fontSize: '12px', color: '#94a3b8', backgroundColor: '#1e293b', padding: '4px 12px', borderRadius: '20px', border: '1px solid #334155' }}>v1.1.0-Stream</span>
                </div>
                <p style={{ color: '#94a3b8', margin: '0 0 32px 0', fontSize: '15px' }}>Run Indian SME workflows across GeM, GST, Udyam, documents, and public business portals with live audit logs.</p>

                {/* Form Inputs */}
                <form onSubmit={handleLaunch} style={{ display: 'flex', gap: '12px', marginBottom: '32px' }}>
                    <input
                        type="text"
                        placeholder="Try: Find GeM tenders for office chairs in Uttarakhand under 5 lakh"
                        value={goal}
                        onChange={(e) => setGoal(e.target.value)}
                        disabled={loading}
                        style={{ flex: 1, padding: '16px', borderRadius: '10px', border: '1px solid #334155', backgroundColor: '#1e293b', color: '#fff', fontSize: '15px', outline: 'none', transition: 'border-color 0.2s' }}
                    />
                    <button 
                        type="submit" 
                        disabled={loading}
                        style={{ padding: '0 28px', borderRadius: '10px', backgroundColor: loading ? '#0ea5e9' : '#0284c7', color: '#fff', border: 'none', cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '600', fontSize: '15px', transition: 'background-color 0.2s' }}
                    >
                        {loading ? 'Running Workflow...' : 'Launch Karya'}
                    </button>
                </form>

                {/* Live Real-Time Activity Console */}
                {loading || liveLogs.length > 2 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, backgroundColor: '#020617', border: '1px solid #1e293b', borderRadius: '12px', padding: '24px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.3)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', borderBottom: '1px solid #1e293b', paddingBottom: '12px' }}>
                            <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: loading ? '#eab308' : '#22c55e', animate: 'pulse 2s infinite' }} />
                            <span style={{ fontSize: '13px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.5px', color: loading ? '#facc15' : '#4ade80' }}>
                                {loading ? 'Live Operation Stream Running' : 'Operation Terminated Successfully'}
                            </span>
                        </div>
                        
                        {/* Terminal Log Container */}
                        <div style={{ flex: 1, overflowY: 'auto', backgroundColor: '#090d16', borderRadius: '8px', padding: '16px', fontFamily: '"Fira Code", "Courier New", monospace', fontSize: '13px', lineHeight: '1.6', color: '#cbd5e1' }}>
                            {liveLogs.map((log, index) => (
                                <div key={index} style={{ marginBottom: '6px', color: log.toLowerCase().includes('error') || log.toLowerCase().includes('failed') ? '#f87171' : log.toLowerCase().includes('thought') ? '#38bdf8' : '#cbd5e1' }}>
                                    {log}
                                </div>
                            ))}
                            <div ref={consoleEndRef} />
                        </div>
                    </div>
                ) : null}

                {/* Display Final Answer for Viewers */}
                {activeMission && activeMission.status === 'completed' && (
                    <div style={{ marginTop: '32px', padding: '24px', borderRadius: '12px', border: '1px solid #22c55e', backgroundColor: '#031b13', color: '#d9f99d' }}>
                        <h4 style={{ margin: '0 0 12px 0', fontSize: '18px', color: '#86efac' }}>Mission Output</h4>
                        <div style={{ fontSize: '16px', lineHeight: '1.8', whiteSpace: 'pre-wrap' }}>
                            {getActiveAnswer()}
                        </div>
                    </div>
                )}

                {activeMission && activeMission.status === 'failed' && (
                    <div style={{ marginTop: '32px', padding: '24px', borderRadius: '12px', border: '1px solid #f87171', backgroundColor: '#210a12', color: '#fecaca' }}>
                        <h4 style={{ margin: '0 0 12px 0', fontSize: '18px', color: '#fca5a5' }}>Mission Failed</h4>
                        <div style={{ fontSize: '15px', lineHeight: '1.8', whiteSpace: 'pre-wrap' }}>
                            {activeMission.error || 'The mission failed without a detailed error.'}
                        </div>
                    </div>
                )}

                {/* Display Final JSON Result Payload when Completed */}
                {activeMission && activeMission.status === 'completed' && activeMission.data && (
                    <div style={{ marginTop: '24px', padding: '24px', borderRadius: '12px', border: '1px solid #1e293b', backgroundColor: '#1e293b' }}>
                        <h4 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#38bdf8' }}>Structured Mission Data</h4>
                        <pre style={{ backgroundColor: '#0f172a', color: '#38bdf8', padding: '16px', borderRadius: '8px', margin: 0, fontSize: '14px', overflowX: 'auto', border: '1px solid #334155' }}>
                            {JSON.stringify(activeMission.data, null, 2)}
                        </pre>
                    </div>
                )}
            </div>
        </div>
    );
}

import React, { useState, useEffect } from 'react';
import './Dashboard.css';

const Dashboard = () => {
    const [status, setStatus] = useState('STOPPED');
    const [loading, setLoading] = useState(false);

    const checkStatus = async () => {
        try {
            const response = await fetch('http://127.0.0.1:8000/api/status');
            const data = await response.json();
            setStatus(data.running ? 'RUNNING' : 'STOPPED');
        } catch (error) {
            console.error("Error fetching status:", error);
            setStatus('OFFLINE');
        }
    };

    const handleStart = async () => {
        setLoading(true);
        try {
            await fetch('http://127.0.0.1:8000/api/start', { method: 'POST' });
            await checkStatus();
        } catch (error) {
            console.error("Error starting:", error);
        }
        setLoading(false);
    };

    const handleStop = async () => {
        setLoading(true);
        try {
            await fetch('http://127.0.0.1:8000/api/stop', { method: 'POST' });
            await checkStatus();
        } catch (error) {
            console.error("Error stopping:", error);
        }
        setLoading(false);
    };

    // Poll status every 2 seconds
    useEffect(() => {
        checkStatus();
        const interval = setInterval(checkStatus, 2000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="dashboard-container">
            <div className="title-section">
                <h1 className="main-title">ANTIGRAVITY</h1>
                <p className="subtitle">Desktop Automation Systems</p>
            </div>

            <div className="status-card">
                <div className={`status-indicator ${status.toLowerCase()}`}></div>
                <div className="status-text">{status}</div>
            </div>

            <div className="controls-grid">
                <button 
                    className="control-btn start" 
                    onClick={handleStart}
                    disabled={status === 'RUNNING' || loading}
                >
                    <span className="btn-icon">▶</span>
                    <span className="btn-label">Start System</span>
                </button>

                <button 
                    className="control-btn stop" 
                    onClick={handleStop}
                    disabled={status === 'STOPPED' || loading}
                >
                    <span className="btn-icon">⏹</span>
                    <span className="btn-label">Emergency Stop</span>
                </button>
            </div>
        </div>
    );
};

export default Dashboard;

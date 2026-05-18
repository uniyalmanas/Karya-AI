import express from 'express';
import { runAutonomousMission, handleAgentTelemetryStream } from '../controllers/agentController.js';
import Mission from '../models/Mission.js';

const router = express.Router();

// 1. Existing launch endpoint
router.post('/run', runAutonomousMission);

// 2. NEW: High-speed telemetry hook for FastAPI stream logs
router.post('/telemetry-stream', handleAgentTelemetryStream);

// 3. Existing UI History sync endpoint
router.get('/history', async (req, res) => {
    try {
        const pastMissions = await Mission.find().sort({ createdAt: -1 }).limit(20);
        return res.status(200).json({ success: true, missions: pastMissions });
    } catch (err) {
        return res.status(500).json({ success: false, error: err.message });
    }
});

export default router;
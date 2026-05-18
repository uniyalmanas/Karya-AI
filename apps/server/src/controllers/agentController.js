import Mission from '../models/Mission.js';
import missionQueue from '../missionQueue.js';

export const runAutonomousMission = async (req, res) => {
  const goal = typeof req.body.goal === 'string' ? req.body.goal.trim() : '';

  if (!goal) {
    return res.status(400).json({ success: false, error: 'Goal directive required.' });
  }

  let newMission;
  try {
    newMission = await Mission.create({ goal, status: 'queued' });
  } catch (dbErr) {
    console.error(`Atlas write failed: ${dbErr.message}`);
    return res.status(500).json({ success: false, error: 'Could not create mission.' });
  }

  const missionIdStr = newMission._id.toString();
  missionQueue.enqueueMission({ missionId: missionIdStr, goal });

  return res.status(202).json({
    success: true,
    missionId: missionIdStr,
    status: 'queued'
  });
};

export const handleAgentTelemetryStream = async (req, res) => {
  const { mission_id, log_line, status, data, error } = req.body;
  const io = req.app.get('io');

  if (!mission_id) {
    return res.status(400).json({ success: false, error: 'mission_id is required.' });
  }

  if (log_line && io) {
    io.emit('mission-step', {
      missionId: mission_id,
      log: log_line
    });
  }

  if (status) {
    const updatePayload = { status };

    if (status === 'completed') {
      updatePayload.extractedData = data || {};
      updatePayload.data = data || {};
    }

    if (status === 'failed') {
      updatePayload.errorLogs = error || 'Unknown failure from agent bridge.';
    }

    try {
      await Mission.findByIdAndUpdate(mission_id, updatePayload, { new: true, timestamps: false });
    } catch (dbErr) {
      console.error(`Failed to update mission ${mission_id} status:`, dbErr.message);
    }

    if (io) {
      io.emit('mission-complete', {
        missionId: mission_id,
        status,
        data: data || null,
        error: error || null
      });
    }
  }

  return res.status(200).json({ success: true });
};

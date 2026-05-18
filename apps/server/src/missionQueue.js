import EventEmitter from 'events';
import axios from 'axios';
import Mission from './models/Mission.js';

const queue = [];
const eventEmitter = new EventEmitter();
const concurrency = Number(process.env.MISSION_QUEUE_CONCURRENCY || 1);
const agentBrainUrl = process.env.AGENT_BRAIN_URL || 'http://127.0.0.1:8000';
let initialized = false;

const enqueueMission = (job) => {
  queue.push(job);
  eventEmitter.emit('job');
};

const nextJob = async () => {
  if (queue.length > 0) {
    return queue.shift();
  }

  return new Promise((resolve) => {
    eventEmitter.once('job', () => resolve(queue.shift()));
  });
};

const processJob = async (job) => {
  const { missionId, goal } = job;
  const mission = await Mission.findById(missionId);

  if (!mission) {
    console.error(`Mission queue failed to resolve id: ${missionId}`);
    return;
  }

  mission.status = 'running';
  await mission.save();

  console.log(`Processing mission ${missionId} from queue`);

  try {
    await axios.post(`${agentBrainUrl}/v1/execute-mission`, {
      goal,
      mission_id: missionId
    }, { timeout: 15000 });
  } catch (error) {
    console.error(`Agent bridge call failed for mission ${missionId}:`, error.message || error);
    mission.status = 'failed';
    mission.errorLogs = error.message || 'Agent bridge call failed';
    await mission.save();
  }
};

const runWorker = async () => {
  while (true) {
    const job = await nextJob();
    if (!job) continue;

    try {
      await processJob(job);
    } catch (error) {
      console.error('Mission queue worker error:', error);
    }
  }
};

const initMissionQueue = () => {
  if (initialized) return;
  initialized = true;

  for (let i = 0; i < concurrency; i += 1) {
    runWorker();
  }
};

export default {
  enqueueMission,
  initMissionQueue
};

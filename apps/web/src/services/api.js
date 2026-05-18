import axios from 'axios';

const API = axios.create({
    baseURL: 'http://localhost:5001/api/agent',
    headers: {
        'Content-Type': 'application/json'
    }
});

// Clean, modular service functions matching your backend routes
export const fetchMissions = async () => {
    const response = await API.get('/history');
    return {
        ...response.data,
        missions: response.data.missions || response.data.history || []
    };
};

export const launchMission = async (goal) => {
    const response = await API.post('/run', { goal });
    return response.data;
};
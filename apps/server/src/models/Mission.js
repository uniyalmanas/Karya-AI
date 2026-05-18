import mongoose from 'mongoose';

const MissionSchema = new mongoose.Schema({
    goal: {
        type: String,
        required: true,
        trim: true
    },
    status: {
        type: String,
        enum: ['queued', 'pending', 'running', 'completed', 'failed'],
        default: 'queued'
    },
    extractedData: {
        type: mongoose.Schema.Types.Mixed,
        default: {}
    },
    data: {
        type: mongoose.Schema.Types.Mixed,
        default: {}
    },
    errorLogs: {
        type: String,
        default: null
    }
}, {
    timestamps: true
});

export default mongoose.model('Mission', MissionSchema);
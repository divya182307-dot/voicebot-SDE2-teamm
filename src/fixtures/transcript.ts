
import type { TranscriptMessage } from '../types/session'

export const mockTranscript: TranscriptMessage[] = [
  {
    id: 1,
    speaker: 'Student',
    text: 'Hello, can you explain artificial intelligence?',
    timestamp: '10:00 AM',
  },
  {
    id: 2,
    speaker: 'AI Assistant',
    text: 'Artificial intelligence allows machines to perform tasks that normally require human intelligence.',
    timestamp: '10:01 AM',
  },
  {
    id: 3,
    speaker: 'Student',
    text: 'Can you give me a simple example?',
    timestamp: '10:02 AM',
  },
  {
    id: 4,
    speaker: 'AI Assistant',
    text: 'A voice assistant that answers your questions is an example of artificial intelligence.',
    timestamp: '10:03 AM',
  },
]

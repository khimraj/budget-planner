// Global state
let selectedFile = null;
let livekitRoom = null;
let isConnected = false;

// Upload page functionality
if (document.getElementById('upload-area')) {
    initUploadPage();
}

// Transactions page functionality
if (document.getElementById('transactions-list')) {
    initTransactionsPage();
}

function initUploadPage() {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const uploadBtn = document.getElementById('upload-btn');
    const voiceBtn = document.getElementById('voice-btn');
    const messageDiv = document.getElementById('message');
    const loadingDiv = document.getElementById('loading');
    const statusText = document.getElementById('status-text');

    // Click to select file
    uploadArea.addEventListener('click', () => fileInput.click());

    // Handle file selection (don't upload yet)
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFileSelection(fileInput.files[0]);
        }
    });

    // Handle upload button click
    uploadBtn.addEventListener('click', () => {
        if (selectedFile) {
            uploadFile(selectedFile);
        } else {
            // If no file selected yet, open picker
            fileInput.click();
        }
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');

        if (e.dataTransfer.files.length > 0) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    // Voice button
    voiceBtn.addEventListener('click', () => {
        window.location.href = '/transactions';
    });

    function handleFileSelection(file) {
        if (!file.name.toLowerCase().endsWith('.csv')) {
            showMessage('Please upload a CSV file only.', 'error');
            return;
        }

        selectedFile = file;
        showMessage(`Selected: ${file.name}`, 'success');
        statusText.textContent = 'Click "Upload File" to proceed';
    }

    async function uploadFile(file) {
        if (!file) return;

        // Show loading
        loadingDiv.classList.remove('hidden');
        messageDiv.classList.add('hidden');
        statusText.textContent = 'Processing...';

        // Upload file
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                showMessage(`✓ ${data.message}`, 'success');
                statusText.textContent = 'Ready to chat';
                voiceBtn.disabled = false;

                // Auto-redirect to transactions page after 1 second
                setTimeout(() => {
                    window.location.href = '/transactions';
                }, 1000);
            } else {
                showMessage(`✗ ${data.error || 'Upload failed'}`, 'error');
                statusText.textContent = 'Upload failed';
                voiceBtn.disabled = true;
            }
        } catch (error) {
            console.error('Upload error:', error);
            showMessage(`✗ Upload failed: ${error.message}`, 'error');
            statusText.textContent = 'Error occurred';
            voiceBtn.disabled = true;
        } finally {
            loadingDiv.classList.add('hidden');
        }
    }

    function showMessage(text, type) {
        messageDiv.textContent = text;
        messageDiv.className = `message message-${type}`;
        messageDiv.classList.remove('hidden');
    }
}

function initTransactionsPage() {
    const voiceControlBtn = document.getElementById('voice-control-btn');
    const statusIndicator = document.getElementById('status-indicator');
    const statusLabel = document.getElementById('status-label');
    const voiceContainer = document.getElementById('voice-container');

    voiceControlBtn.addEventListener('click', toggleVoiceAgent);

    async function toggleVoiceAgent() {
        if (isConnected) {
            disconnectVoiceAgent();
        } else {
            await connectVoiceAgent();
        }
    }

    async function connectVoiceAgent() {
        try {
            voiceControlBtn.disabled = true;
            voiceControlBtn.textContent = 'Connecting...';

            // Get LiveKit token
            const response = await fetch('/api/livekit-token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to get token');
            }

            const { token, url, room } = await response.json();

            // Connect to LiveKit room
            const LiveKit = window.LivekitClient || window.LiveKit || window.livekit;

            if (!LiveKit) {
                throw new Error('LiveKit SDK not loaded. Please refresh the page.');
            }

            livekitRoom = new LiveKit.Room({
                adaptiveStream: true,
                dynacast: true,
            });

            // Set up audio level monitoring with Web Audio API
            const audioLevelBar = document.getElementById('audio-level-bar');
            const voiceStatusText = document.getElementById('voice-status-text');
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();

            let userAudioLevel = 0;
            let agentAudioLevel = 0;
            let userAnalyzer = null;
            let agentAnalyzers = new Map();
            let animationFrameId = null;

            // Function to calculate RMS (Root Mean Square) audio level
            function calculateAudioLevel(analyzer) {
                const dataArray = new Uint8Array(analyzer.frequencyBinCount);
                analyzer.getByteFrequencyData(dataArray);

                // Calculate RMS from frequency data
                let sum = 0;
                for (let i = 0; i < dataArray.length; i++) {
                    sum += dataArray[i] * dataArray[i];
                }
                const rms = Math.sqrt(sum / dataArray.length);

                // Normalize to 0-1 range and apply sensitivity
                return Math.min((rms / 128) * 1.5, 1.0);
            }

            // Animation loop for smooth audio visualization
            function updateAudioVisualization() {
                // Get current audio levels
                let displayLevel = 0;
                let currentState = 'idle';

                if (userAnalyzer) {
                    userAudioLevel = calculateAudioLevel(userAnalyzer);
                    // Apply noise gate
                    if (userAudioLevel < 0.05) { // Increased noise gate threshold
                        userAudioLevel = 0;
                    }
                }

                // Calculate max agent level from all agent tracks
                agentAudioLevel = 0;
                agentAnalyzers.forEach(analyzer => {
                    let level = calculateAudioLevel(analyzer);
                    // Apply noise gate for agent too
                    if (level < 0.05) {
                        level = 0;
                    }
                    agentAudioLevel = Math.max(agentAudioLevel, level);
                });

                // Determine active speaker with hysteresis/ducking
                // If agent is speaking significantly, raise user threshold to avoid echo
                let userThreshold = 0;
                if (agentAudioLevel > 0.05) {
                    userThreshold = 0.4; // Higher threshold for user when agent is talking (ducking)
                }

                // Apply strict priority
                let userIsSpeaking = userAudioLevel > userThreshold;
                let agentIsSpeaking = agentAudioLevel > 0;

                if (userIsSpeaking) {
                    displayLevel = userAudioLevel * 100;
                    currentState = 'user';
                    audioLevelBar.classList.add('user-speaking');
                    audioLevelBar.classList.remove('agent-speaking');
                    voiceStatusText.textContent = 'You are speaking...';
                } else if (agentIsSpeaking) {
                    displayLevel = agentAudioLevel * 100;
                    currentState = 'agent';
                    audioLevelBar.classList.add('agent-speaking');
                    audioLevelBar.classList.remove('user-speaking');
                    voiceStatusText.textContent = 'Agent is speaking...';
                } else {
                    // Smooth decay to 0
                    const currentWidth = parseFloat(audioLevelBar.style.width) || 0;
                    displayLevel = currentWidth * 0.8; // Decay factor
                    if (displayLevel < 1) { // Snap to 0 if very low
                        displayLevel = 0;
                        audioLevelBar.classList.remove('user-speaking', 'agent-speaking');
                        voiceStatusText.textContent = 'Listening...';
                    }
                }

                // Update the bar width
                audioLevelBar.style.width = `${displayLevel}%`;

                // Continue animation loop
                animationFrameId = requestAnimationFrame(updateAudioVisualization);
            }

            // Track local (user) audio with Web Audio API
            livekitRoom.on('localTrackPublished', async (publication) => {
                if (publication.kind === 'audio' && publication.track) {
                    console.log('Local audio track published');
                    try {
                        const mediaStream = publication.track.mediaStream;
                        if (mediaStream) {
                            const source = audioContext.createMediaStreamSource(mediaStream);
                            userAnalyzer = audioContext.createAnalyser();
                            userAnalyzer.fftSize = 256;
                            userAnalyzer.smoothingTimeConstant = 0.8;
                            source.connect(userAnalyzer);
                            console.log('User audio analyzer connected');
                        }
                    } catch (error) {
                        console.error('Failed to setup user audio analyzer:', error);
                    }
                }
            });

            // Handle track subscriptions (agent audio)
            livekitRoom.on('trackSubscribed', (track, publication, participant) => {
                console.log('Track subscribed:', track.kind, participant.identity);

                // Attach the track to the DOM for playback
                const element = track.attach();
                document.body.appendChild(element);

                // Setup Web Audio API analyzer for agent audio
                if (track.kind === 'audio') {
                    try {
                        const mediaStream = track.mediaStream;
                        if (mediaStream) {
                            const source = audioContext.createMediaStreamSource(mediaStream);
                            const analyzer = audioContext.createAnalyser();
                            analyzer.fftSize = 256;
                            analyzer.smoothingTimeConstant = 0.8;
                            source.connect(analyzer);
                            agentAnalyzers.set(track.sid, analyzer);
                            console.log('Agent audio analyzer connected');
                        }
                    } catch (error) {
                        console.error('Failed to setup agent audio analyzer:', error);
                    }
                }
            });

            livekitRoom.on('trackUnsubscribed', (track, publication, participant) => {
                console.log('Track unsubscribed:', track.kind, participant.identity);

                // Clean up agent audio analyzer
                if (agentAnalyzers.has(track.sid)) {
                    agentAnalyzers.delete(track.sid);
                }

                // Detach and remove the element
                track.detach().forEach(element => element.remove());
            });

            livekitRoom.on('disconnected', () => {
                console.log('Room disconnected');

                // Stop animation loop
                if (animationFrameId) {
                    cancelAnimationFrame(animationFrameId);
                }

                // Clean up audio context
                userAnalyzer = null;
                agentAnalyzers.clear();

                disconnectVoiceAgent();
            });

            await livekitRoom.connect(url, token);
            console.log('Connected to room');

            // Enable microphone after connecting
            try {
                await livekitRoom.localParticipant.setMicrophoneEnabled(true);
                console.log('Microphone enabled and publishing');
            } catch (error) {
                console.error('Failed to enable microphone:', error);
                throw new Error('Failed to enable microphone. Please check browser permissions.');
            }

            // Start the visualization loop
            updateAudioVisualization();

            isConnected = true;
            updateConnectionStatus(true);
            voiceContainer.classList.remove('hidden');
            voiceControlBtn.textContent = 'Disconnect Voice Agent';
            voiceControlBtn.disabled = false;
            voiceControlBtn.classList.add('connected');

        } catch (error) {
            console.error('Voice connection error:', error);
            alert(`Failed to connect: ${error.message}`);
            voiceControlBtn.textContent = 'Start Voice Chat';
            voiceControlBtn.disabled = false;
        }
    }

    function disconnectVoiceAgent() {
        if (livekitRoom) {
            livekitRoom.disconnect();
            livekitRoom = null;
        }

        isConnected = false;
        updateConnectionStatus(false);
        voiceContainer.classList.add('hidden');
        voiceControlBtn.textContent = 'Start Voice Chat';
        voiceControlBtn.classList.remove('connected');
    }

    function updateConnectionStatus(connected) {
        if (connected) {
            statusIndicator.classList.add('connected');
            statusLabel.textContent = 'Connected';
        } else {
            statusIndicator.classList.remove('connected');
            statusLabel.textContent = 'Disconnected';
        }
    }
}

async function loadTransactions() {
    const transactionsList = document.getElementById('transactions-list');
    const loadingDiv = document.getElementById('transactions-loading');
    const errorDiv = document.getElementById('transactions-error');
    const emptyState = document.getElementById('empty-state');

    if (!transactionsList) return;

    try {
        loadingDiv.classList.remove('hidden');
        errorDiv.classList.add('hidden');
        emptyState.classList.add('hidden');

        const response = await fetch('/api/transactions');
        const data = await response.json();

        loadingDiv.classList.add('hidden');

        if (!data.transactions || data.transactions.length === 0) {
            emptyState.classList.remove('hidden');
            return;
        }

        // Render transactions
        transactionsList.innerHTML = data.transactions.map(transaction => {
            const amount = parseFloat(transaction.Amount);
            const amountClass = amount >= 0 ? 'positive' : 'negative';
            const amountPrefix = amount >= 0 ? '+' : '';
            const formattedAmount = `${amountPrefix}$${Math.abs(amount).toFixed(2)}`;

            return `
                <div class="transaction-card">
                    <div class="transaction-info">
                        <div class="transaction-description">${escapeHtml(transaction.Description)}</div>
                        <div class="transaction-meta">
                            <span class="transaction-date">${transaction.Date}</span>
                            <span class="transaction-category">${transaction.Category}</span>
                        </div>
                    </div>
                    <div class="transaction-amount ${amountClass}">
                        ${formattedAmount}
                    </div>
                </div>
            `;
        }).join('');

    } catch (error) {
        console.error('Error loading transactions:', error);
        loadingDiv.classList.add('hidden');
        errorDiv.textContent = `Failed to load transactions: ${error.message}`;
        errorDiv.classList.remove('hidden');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

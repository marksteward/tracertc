var pc = null;
var dc = null;
const debug = true;

function createPeerConnection() {
    const config = { iceServers: [
    //    { urls: 'stun:stun.l.google.com:19302' },
    ]};

    pc = new RTCPeerConnection(config);

    if (debug) {
        const onicegatheringstatechange = evt => console.log('iceGatheringState: ' + pc.iceGatheringState);
        const oniceconnectionstatechange = evt => console.log('iceConnectionState: ' + pc.iceConnectionState);
        const onsignalingstatechange = evt => console.log('signalingState: ' + pc.signalingState);

        pc.addEventListener('icegatheringstatechange', onicegatheringstatechange);
        pc.addEventListener('iceconnectionstatechange', oniceconnectionstatechange);
        pc.addEventListener('signalingstatechange', onsignalingstatechange);

        onicegatheringstatechange();
        oniceconnectionstatechange();
        onsignalingstatechange();
    }

    return pc;
}

function negotiate() {
    if (document.location.hash == '#offer') {
        pc.createOffer()  // No need to wait for ice, we only want to connect out
            .then(desc => pc.setLocalDescription(desc))
            .then(function() {
                const offer = pc.localDescription;
                return fetch('/offer', {
                    body: JSON.stringify({ sdp: offer.sdp }),
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    method: 'POST'
                });
            })
            .then(response => response.json())
            .then(answer => pc.setRemoteDescription(answer))
            .catch(e => alert(e));
    } else {
        fetch('/create-offer', {
            body: JSON.stringify({}),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        })
            .then(response => response.json())
            .then(desc => pc.setRemoteDescription(desc))
            .then(desc => pc.createAnswer())
            .then(desc => pc.setLocalDescription(desc))
            .then(function() {
                const answer = pc.localDescription;
                return fetch('/answer', {
                    body: JSON.stringify({ sdp: answer.sdp }),
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    method: 'POST'
                });
            })
            .catch(e => alert(e));
    }
}

document.getElementById('start').addEventListener('click', evt => {
    pc = createPeerConnection();

    const processProbes = chan => {
        if (debug) {
            chan.addEventListener('open', evt => console.log('Channel (re)open', evt));
            chan.addEventListener('close', evt => console.log('Channel closed', evt));
        }
        chan.addEventListener('message', evt => {
            console.log('message', evt);
            if (evt.data.startsWith('ping')) {
                chan.send('pong ' + evt.data.substring(5));
            } else if (evt.data.startsWith('trace')) {
                document.getElementById('trace').innerText = evt.data.substring(7);
            }
        });
    }

    if (document.location.hash == '#offer') {
        const parameters = {'maxRetransmits': 0, 'ordered': false};
        dc = pc.createDataChannel('probes', parameters);
        processProbes(dc);
    }

    pc.addEventListener('datachannel', evt => {
        console.log('Remote created a data channel', evt);
        dc = evt.channel;
        processProbes(dc);
    });

    negotiate();
});

document.getElementById('stop').addEventListener('click', evt => {
    if (dc) {
        dc.close();
    }
    pc.close();
});


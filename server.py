import argparse
import asyncio
import json
import logging
import os
import uuid

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

from tracertc import Tracer

ROOT = os.path.dirname(__file__)

logger = logging.getLogger('server')
pcs = set()
routes = web.RouteTableDef()


@routes.get('/')
async def index(request):
    content = open(os.path.join(ROOT, 'index.html'), 'r').read()
    return web.Response(content_type='text/html', text=content)

@routes.get('/client.js')
async def javascript(request):
    content = open(os.path.join(ROOT, 'client.js'), 'r').read()
    return web.Response(content_type='application/javascript', text=content)

@routes.post('/offer')
async def offer(request):
    params = await request.json()
    sdp = params['sdp']
    offer = RTCSessionDescription(sdp=sdp, type='offer')

    # TODO: strip remote IPs so we know they're connecting to us

    config = RTCConfiguration(iceServers=[
        RTCIceServer(urls=['stun:stun.l.google.com:19302']),
    ])
    pc = RTCPeerConnection(config)
    pcs.add(pc)

    # TODO: wait for STUN to complete

    logger.info(f"Created for {request.remote}")

    @pc.on('datachannel')
    def on_datachannel(channel):
        asyncio.ensure_future(trace_forever(channel))

    @pc.on('iceconnectionstatechange')
    async def on_iceconnectionstatechange():
        logger.info(f"iceConnectionState: {pc.iceConnectionState}")
        if pc.iceConnectionState == 'failed':
            await pc.close()
            pcs.discard(pc)

    await pc.setRemoteDescription(offer)
    await pc.setLocalDescription(await pc.createAnswer())

    return web.Response(
        content_type='application/json',
        text=json.dumps(
            {'sdp': pc.localDescription.sdp, 'type': 'answer'}
        ),
    )

@routes.post('/create-offer')
async def create_offer(request):
    global pc
    pc = RTCPeerConnection()
    pcs.add(pc)

    channel = pc.createDataChannel('probes', maxRetransmits=0, ordered=False)

    @channel.on('open')
    def on_open():
        asyncio.ensure_future(trace_forever(channel))

    @pc.on('iceconnectionstatechange')
    async def on_iceconnectionstatechange():
        logger.info(f"iceConnectionState: {pc.iceConnectionState}")
        if pc.iceConnectionState == 'failed':
            await pc.close()
            pcs.discard(pc)

    await pc.setLocalDescription(await pc.createOffer())
    return web.Response(
        content_type='application/json',
        text=json.dumps(
            {'sdp': pc.localDescription.sdp, 'type': 'offer'}
        ),
    )

@routes.post('/answer')
async def answer(request):
    params = await request.json()
    sdp = params['sdp']
    answer = RTCSessionDescription(sdp=sdp, type='answer')

    # TODO: strip remote IPs so we know they're connecting to us

    logger.info(f"Created for {request.remote}")

    await pc.setRemoteDescription(answer)

    #pc.sctp.transport.transport.addRemoteCandidate(None)
    #pc.sctp.transport.transport._connection._remote_candidates_end = True

    return web.Response(
        content_type='application/json',
        text=json.dumps(
            {'sdp': pc.localDescription.sdp, 'type': 'final'}
        ),
    )

async def trace_forever(channel):
    tracer = Tracer(channel)
    while True:
        trace = await tracer.send_probes()
        result = json.dumps(trace)
        channel.send('trace ' + result)
        logger.info(f"Trace complete, sleeping")
        logger.info(f"Trace result {trace}")
        await asyncio.sleep(10)

async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    await asyncio.wait(coros)
    pcs.clear()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.add_routes(routes)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, access_log=None, port=args.port)


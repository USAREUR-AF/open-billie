import { randomUUID } from 'node:crypto';
import * as dgram from 'node:dgram';
import * as net from 'node:net';
import { OetfDecoder, type DecodedRecord, type FramingError } from '@open-billie/decoder-oetf';
import { mapOetfRecord } from '@open-billie/mappings-oetf';
const OUTPUTS = [
  { outputName: 'tracks-cot', format: 'cot' },
  { outputName: 'tracks-cat062', format: 'asterix-cat062' },
  { outputName: 'tracks-sapient', format: 'sapient' },
];
const runningSockets = new Set<net.Socket>();
let stopping = false;

function sendTranslation(socketPath: string, outputName: string, format: string, record: unknown): Promise<void> {
  const requestId = randomUUID();
  const line = Buffer.from(JSON.stringify({
    apiVersion: 'billie.dev/translation-v1',
    kind: 'TranslateRequest',
    requestId,
    kid: 'oetf',
    target: { outputName, format },
    record,
  }) + '\n');

  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let response = Buffer.alloc(0);
    let responseAccepted = false;
    const timeout = setTimeout(() => socket.destroy(new Error('translator response timed out')), 10_000);
    const done = (error?: Error) => {
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve();
    };
    socket.once('error', done);
    socket.on('data', (chunk: Buffer) => {
      response = Buffer.concat([response, chunk]);
      if (response.length > 64 * 1024) {
        socket.destroy(new Error('translator response exceeded 64 KiB'));
        return;
      }
      const newline = response.indexOf(0x0a);
      if (newline < 0) return;
      try {
        const result = JSON.parse(response.subarray(0, newline).toString('utf8')) as Record<string, unknown>;
        if (result.requestId !== requestId) throw new Error('translator response requestId did not match');
        if (result.status !== 'published') {
          const error = result.error as { code?: string; message?: string } | undefined;
          throw new Error(`translator rejected output (${error?.code ?? 'unknown'}): ${error?.message ?? 'no error detail provided'}`);
        }
        if (result.outputName !== outputName || result.format !== format) {
          throw new Error('translator response output selection did not match');
        }
        responseAccepted = true;
        console.log(`translator accepted output=${outputName} format=${format} bytes=${String(result.bytesPublished ?? 0)}`);
        socket.end();
      } catch (error) {
        socket.destroy(error instanceof Error ? error : new Error(String(error)));
      }
    });
    socket.once('close', () => done(responseAccepted ? undefined : new Error('translator closed before returning a complete response')));
    socket.write(line);
  });
}

async function publishRecord(socketPath: string, decoded: DecodedRecord): Promise<void> {
  for (const canonical of mapOetfRecord(decoded)) {
    const track = canonical.fields;
    for (const output of OUTPUTS) {
      try {
        await sendTranslation(socketPath, output.outputName, output.format, track);
      } catch (error) {
        console.error(`OETF output ${output.outputName} failed: ${String(error)}`);
      }
    }
  }
}

function reportFramingErrors(decoder: OetfDecoder): void {
  for (const error of decoder.getRecentErrors()) {
    const issue = error as FramingError;
    console.error(`OETF framing ${issue.reason}: ${issue.detail ?? ''}`);
  }
}

function createConsumer(decoder: OetfDecoder, socketPath: string): (chunk: Buffer) => void {
  let outputQueue = Promise.resolve();
  let queuedRecords = 0;
  return (chunk: Buffer) => {
    for (const record of decoder.feed(chunk)) {
      if (queuedRecords >= 256) {
        console.error('OETF output queue is full; dropping decoded record');
        continue;
      }
      queuedRecords += 1;
      outputQueue = outputQueue
        .then(() => publishRecord(socketPath, record))
        .catch((error: unknown) => {
          console.error(`OETF mapping failed: ${error instanceof Error ? error.message : String(error)}`);
        })
        .finally(() => { queuedRecords -= 1; });
    }
    reportFramingErrors(decoder);
  };
}

function runTcp(bindHost: string, port: number, socketPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const server = net.createServer((client) => {
      const decoder = new OetfDecoder();
      const consume = createConsumer(decoder, socketPath);
      runningSockets.add(client);
      console.log(`OETF TCP connected from ${client.remoteAddress}:${client.remotePort}`);
      client.on('data', consume);
      client.on('error', (error) => console.error(`OETF TCP connection error: ${error.message}`));
      client.on('close', () => {
        reportFramingErrors(decoder);
        if (decoder.getPendingBytes() > 0) {
          console.error(`OETF TCP stream ended with ${decoder.getPendingBytes()} incomplete frame byte(s); discarding them`);
        }
        decoder.reset();
        runningSockets.delete(client);
        console.log(`OETF TCP disconnected from ${client.remoteAddress}:${client.remotePort}`);
      });
    });
    server.maxConnections = 8;
    server.once('error', reject);
    server.listen(port, bindHost, () => console.log(`OETF TCP listening on ${bindHost}:${port}; translator socket ${socketPath}`));
    const close = () => {
      stopping = true;
      for (const client of runningSockets) client.destroy();
      server.close(() => resolve());
    };
    process.once('SIGINT', close);
    process.once('SIGTERM', close);
  });
}

function runUdp(bindHost: string, port: number, socketPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const server = dgram.createSocket('udp4');
    const decoder = new OetfDecoder();
    const consume = createConsumer(decoder, socketPath);
    server.on('error', (error) => {
      console.error(`OETF UDP error: ${error.message}`);
      server.close();
      reject(error);
    });
    server.on('message', consume);
    server.bind(port, bindHost, () => console.log(`OETF UDP listening on ${bindHost}:${port}; translator socket ${socketPath}`));
    const close = () => {
      stopping = true;
      server.close(() => resolve());
    };
    process.once('SIGINT', close);
    process.once('SIGTERM', close);
  });
}

async function main(): Promise<void> {
  const bindHost = process.env.BILLIE_INPUT_BIND ?? '0.0.0.0';
  const port = Number(process.env.BILLIE_INPUT_PORT ?? '5100');
  const transport = (process.env.BILLIE_INPUT_TRANSPORT ?? 'udp').toLowerCase();
  const socketPath = process.env.BILLIE_TRANSLATOR_SOCKET ?? '/run/billie/translator.sock';
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('BILLIE_INPUT_PORT must be between 1 and 65535');
  if (transport === 'tcp') await runTcp(bindHost, port, socketPath);
  else if (transport === 'udp') await runUdp(bindHost, port, socketPath);
  else throw new Error(`unsupported BILLIE_INPUT_TRANSPORT '${transport}' (use udp or tcp)`);
}

void main().catch((error: unknown) => {
  if (!stopping) {
    console.error(`OETF runtime failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
});

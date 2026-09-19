import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

import { configureLife } from './config.js';
import Life from './upstream/src/modules/life.js';
import $lang from './upstream/src/i18n/zh-cn.js';

const ENGINE_VERSION = '1.0.0';
const UPSTREAM_COMMIT = '3c218603839339ead6b0381586eea3f1d7e5250d';
const ROOT = dirname(fileURLToPath(import.meta.url));
const dataCache = new Map();

globalThis.$lang = $lang;

function seededRandom(seed) {
    let h = 2166136261 >>> 0;
    for (const ch of String(seed)) {
        h ^= ch.codePointAt(0);
        h = Math.imul(h, 16777619);
    }
    return () => {
        h += 0x6D2B79F5;
        let t = h;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

async function loadJson(relativePath) {
    if (!dataCache.has(relativePath)) {
        const raw = await readFile(join(ROOT, 'upstream', 'data', `${relativePath}.json`), 'utf8');
        dataCache.set(relativePath, JSON.parse(raw));
    }
    return structuredClone(dataCache.get(relativePath));
}

function installProfile(profile = {}) {
    const values = { ...profile };
    globalThis.localStorage = {
        getItem(key) {
            return Object.hasOwn(values, key) ? values[key] : null;
        },
        setItem(key, value) {
            values[key] = String(value);
        },
        removeItem(key) {
            delete values[key];
        },
    };
    return () => ({ ...values });
}

function installEvents(unlocked) {
    globalThis.$$eventMap = new Map();
    globalThis.$$event = (tag, data) => {
        const listeners = globalThis.$$eventMap.get(tag);
        if (listeners) listeners.forEach(fn => fn(data));
    };
    globalThis.$$on = (tag, fn) => {
        let listeners = globalThis.$$eventMap.get(tag);
        if (!listeners) {
            listeners = new Set();
            globalThis.$$eventMap.set(tag, listeners);
        }
        listeners.add(fn);
    };
    globalThis.$$off = (tag, fn) => globalThis.$$eventMap.get(tag)?.delete(fn);
    globalThis.$$on('achievement', ({ id, name, description, grade }) => {
        unlocked.push({ id, name, description, grade });
    });
}

async function createLife(profile) {
    const unlocked = [];
    const exportProfile = installProfile(profile);
    installEvents(unlocked);
    const life = new Life();
    configureLife(life);
    await life.initial(
        name => loadJson(`zh-cn/${name}`),
        name => loadJson(name),
    );
    return { life, unlocked, exportProfile };
}

function publicTalent(talent, index) {
    return {
        index,
        id: talent.id,
        name: talent.name,
        description: talent.description,
        grade: talent.grade,
    };
}

function selectTalents(life, talents, indexes) {
    if (!Array.isArray(indexes) || indexes.length !== 4) {
        throw new Error('必须选择恰好 4 个天赋');
    }
    const normalized = indexes.map(Number);
    if (new Set(normalized).size !== 4 || normalized.some(i => !Number.isInteger(i) || i < 1 || i > talents.length)) {
        throw new Error('天赋编号必须是 1 到 15 之间不重复的整数');
    }
    const selected = normalized.map(i => talents[i - 1]);
    for (let i = 0; i < selected.length; i++) {
        const previous = selected.slice(0, i).map(t => t.id);
        const exclusive = life.exclude(previous, selected[i].id);
        if (exclusive != null) {
            const conflict = selected.find(t => t.id === exclusive);
            throw new Error(`天赋【${selected[i].name}】与【${conflict?.name ?? exclusive}】冲突`);
        }
    }
    return selected;
}

function validateAllocation(allocation, total) {
    const result = {};
    for (const key of ['CHR', 'INT', 'STR', 'MNY']) {
        const value = Number(allocation?.[key]);
        if (!Number.isInteger(value) || value < 0 || value > 15) {
            throw new Error(`${key} 必须是 0 到 15 之间的整数`);
        }
        result[key] = value;
    }
    const sum = Object.values(result).reduce((a, b) => a + b, 0);
    if (sum !== total) throw new Error(`属性点之和必须等于 ${total}，当前为 ${sum}`);
    return { ...result, SPR: 5 };
}

function trajectoryEntry({ age, content }) {
    const lines = [];
    for (const item of content) {
        if (item.type === 'TLT') {
            lines.push(`天赋【${item.name}】发动：${item.description}`);
        } else if (item.type === 'EVT') {
            lines.push(item.description + (item.postEvent ? `\n${item.postEvent}` : ''));
        }
    }
    return { age, text: `${age}岁：${lines.join('\n')}` };
}

function summaryData(life) {
    const labels = {
        HCHR: '运气', HINT: '智力', HSTR: '体质', HMNY: '家境',
        HSPR: '精神力', HAGE: '享年', SUM: '总评',
    };
    const summary = life.summary;
    return Object.fromEntries(Object.entries(labels).map(([key, label]) => {
        const item = summary[key];
        return [key, {
            label,
            value: item.value,
            grade: item.grade,
            judge: item.judge ? ($lang[item.judge] ?? item.judge) : '',
        }];
    }));
}

async function seeded(seed, fn) {
    const original = Math.random;
    Math.random = seededRandom(seed);
    try {
        return await fn();
    } finally {
        Math.random = original;
    }
}

async function draw(request) {
    return seeded(request.seed, async () => {
        const { life, exportProfile } = await createLife(request.profile);
        const talents = life.talentRandom();
        return {
            talents: talents.map((talent, index) => publicTalent(talent, index + 1)),
            profile: exportProfile(),
        };
    });
}

async function prepare(request) {
    return seeded(request.seed, async () => {
        const { life } = await createLife(request.profile);
        const talents = life.talentRandom();
        const selected = selectTalents(life, talents, request.indexes);
        const replacements = life.remake(selected.map(t => t.id));
        return {
            engine: { version: ENGINE_VERSION, upstreamCommit: UPSTREAM_COMMIT },
            selected: selected.map((talent, index) => publicTalent(talent, request.indexes[index])),
            points: life.getPropertyPoints(),
            replacements,
        };
    });
}

async function simulate(request) {
    return seeded(request.seed, async () => {
        const { life, unlocked, exportProfile } = await createLife(request.profile);
        const talents = life.talentRandom();
        const selected = selectTalents(life, talents, request.indexes);
        const replacements = life.remake(selected.map(t => t.id));
        const points = life.getPropertyPoints();
        const allocation = validateAllocation(request.allocation, points);
        life.start(allocation);

        const trajectory = [];
        for (let step = 0; step < 10000; step++) {
            const current = life.next();
            trajectory.push(trajectoryEntry(current));
            if (current.isEnd) break;
            if (step === 9999) throw new Error('人生推演超过安全上限');
        }

        const summary = summaryData(life);
        life.talentExtend(null);
        life.times = life.times + 1;
        return {
            engine: { version: ENGINE_VERSION, upstreamCommit: UPSTREAM_COMMIT },
            selected: selected.map((talent, index) => publicTalent(talent, request.indexes[index])),
            replacements,
            points,
            allocation,
            trajectory,
            summary,
            achievements: unlocked,
            profile: exportProfile(),
        };
    });
}

async function inherit(request) {
    const { life, unlocked, exportProfile } = await createLife(request.profile);
    const talentId = request.talentId == null ? null : Number(request.talentId);
    if (talentId != null) life.getTalent(talentId);
    life.talentExtend(talentId);
    return { profile: exportProfile(), achievements: unlocked };
}

async function handle(request) {
    switch (request.action) {
        case 'ping':
            return { engineVersion: ENGINE_VERSION, upstreamCommit: UPSTREAM_COMMIT, node: process.version };
        case 'draw': return draw(request);
        case 'prepare': return prepare(request);
        case 'simulate': return simulate(request);
        case 'inherit': return inherit(request);
        default: throw new Error(`未知操作：${request.action}`);
    }
}

function writeResponse(response) {
    process.stdout.write(`${JSON.stringify(response)}\n`);
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
let queue = Promise.resolve();
input.on('line', line => {
    queue = queue.then(async () => {
        let request;
        try {
            request = JSON.parse(line);
            const result = await handle(request);
            writeResponse({ id: request.id, ok: true, result });
        } catch (error) {
            writeResponse({
                id: request?.id ?? null,
                ok: false,
                error: error instanceof Error ? error.message : String(error),
            });
        }
    });
});

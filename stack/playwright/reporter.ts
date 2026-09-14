import type {Reporter, TestCase, TestResult, TestStep, FullResult} from '@playwright/test/reporter';
import fs from 'node:fs';
import path from 'node:path';

export default class EvidenceReporter implements Reporter {
    private tests: object[] = [];
    private output = process.env.E2E_OUTPUT || path.resolve('results', process.env.E2E_SUITE!);
    private progress(value: object) {
        fs.mkdirSync(this.output, {recursive: true});
        fs.appendFileSync(path.join(this.output, 'progress.ndjson'), JSON.stringify({...value, at: new Date().toISOString()}) + '\n');
    }
    onTestBegin(test: TestCase) { this.progress({title: test.title, status: 'running'}); }
    onStepBegin(_test: TestCase, _result: TestResult, step: TestStep) {
        if (step.category === 'test.step') this.progress({title: step.title, status: 'running'});
    }
    onStepEnd(_test: TestCase, _result: TestResult, step: TestStep) {
        if (step.category === 'test.step') this.progress({title: step.title, status: step.error ? 'failed' : 'passed', duration: step.duration});
    }
    onTestEnd(test: TestCase, result: TestResult) {
        const evidence = result.attachments.filter(a => a.path).map(a => ({name: a.name, path: path.relative(this.output, a.path!)}));
        this.tests.push({id: test.title.match(/\{([^}]+)\}/)?.[1], suite: process.env.E2E_SUITE,
            title: test.title, status: result.status, duration: result.duration, evidence,
            errors: result.errors.map(e => e.message)});
        this.progress({title: test.title, status: result.status, duration: result.duration});
    }
    onEnd(result: FullResult) {
        fs.mkdirSync(this.output, {recursive: true});
        fs.writeFileSync(path.join(this.output, 'evidence.json'), JSON.stringify({status: result.status, tests: this.tests}, null, 2));
    }
}

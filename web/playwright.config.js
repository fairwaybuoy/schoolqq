import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:30000,workers:1,reporter:'list',use:{baseURL:'http://127.0.0.1:8080',headless:true,launchOptions:{executablePath:process.env.SCHOOLQQ_TEST_CHROMIUM || '/usr/bin/chromium',args:['--no-sandbox']}}});

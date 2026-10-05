import type { APIRoute } from 'astro';
import {jsonResponse,loadOpsStatus} from '../../../lib/server';
export const GET:APIRoute=async()=>jsonResponse(await loadOpsStatus());

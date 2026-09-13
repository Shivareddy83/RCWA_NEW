import type { Role } from '../types';

export const canOperate = (role: Role | undefined): boolean => role === 'ADMIN' || role === 'OPS';
export const canInvestigate = (role: Role | undefined): boolean => role === 'ADMIN' || role === 'OPS' || role === 'ANALYST';
export const canManageUsers = (role: Role | undefined): boolean => role === 'ADMIN';
export const canRetryJobs = (role: Role | undefined): boolean => role === 'ADMIN' || role === 'OPS';
export const canRunReconciliation = canInvestigate;

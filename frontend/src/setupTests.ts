import '@testing-library/jest-dom';

// Mock Supabase environment variables for testing since they are not present in CI environment
process.env.VITE_SUPABASE_URL = 'http://localhost:54321';
process.env.VITE_SUPABASE_ANON_KEY = 'mock-anon-key-for-testing';

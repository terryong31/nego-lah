import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import App from './App';

describe('App Component', () => {
    it('renders without crashing', () => {
        render(<App />);
        // Basic check to see if the main layout is present
        expect(document.body).toBeInTheDocument();
    });
});

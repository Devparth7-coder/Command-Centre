import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title:'AI Command Center', description:'One interface. Every agent. Total control.' };
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="en"><body>{children}</body></html> }
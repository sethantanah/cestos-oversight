import React from 'react';
import type { Metadata, Viewport } from 'next';
import { AuthProvider } from '@/components/AuthProvider';
import '../styles/tailwind.css';
import '../styles/integration.css';
import { Toaster } from 'sonner';

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export const metadata: Metadata = {
  title: 'Cestos Operations — Field Operations Command Platform',
  description: 'Cestos Operations helps mining and drilling companies manage workforce, equipment fleet, and inventory across multiple active projects from one command platform.',
  icons: {
    icon: [
      { url: '/favicon.ico', type: 'image/x-icon' },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" >
      <body>
        <AuthProvider>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              fontFamily: 'var(--font-dm-sans)',
              fontSize: '13px',
              fontWeight: '500',
            },
          }}
        />

        </AuthProvider>
      </body>
    </html>
  );
}

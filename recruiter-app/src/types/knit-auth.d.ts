import type * as React from 'react';

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'knit-auth': React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & {
          authsessiontoken?: string;
          skipintro?: string;
        },
        HTMLElement
      >;
    }
  }
}

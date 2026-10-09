/** The dashboard pages, in sidebar order. */
export const PAGES = [
  { id: 'overview', label: 'Overview', icon: 'overview',
    subtitle: 'Verdict and the points that need a look' },
  { id: 'authenticity', label: 'Authenticity', icon: 'shield',
    subtitle: 'Is the device what it claims to be?' },
  { id: 'health', label: 'Health', icon: 'health',
    subtitle: 'Condition of the components, measured against the specifications' },
  { id: 'tests', label: 'Tests', icon: 'tests',
    subtitle: 'Functional checks, automatic and guided' },
  { id: 'live', label: 'Live sensors', icon: 'live',
    subtitle: 'Streams straight from the hardware' },
  { id: 'specs', label: 'Specifications', icon: 'chip',
    subtitle: 'Everything read from the device' },
  { id: 'raw', label: 'Raw data', icon: 'data',
    subtitle: 'The complete snapshot, as collected' },
];

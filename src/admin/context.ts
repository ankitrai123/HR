import { createContext, useContext } from 'react';

export const OrgContext = createContext('');
export const useOrganization = () => useContext(OrgContext);

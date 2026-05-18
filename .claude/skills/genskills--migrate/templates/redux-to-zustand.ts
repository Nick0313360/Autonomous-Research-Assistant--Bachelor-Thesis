// Before (Redux Toolkit)
const userSlice = createSlice({
  name: 'user',
  initialState: { name: '', loggedIn: false },
  reducers: {
    login(state, action: PayloadAction<string>) {
      state.name = action.payload;
      state.loggedIn = true;
    },
    logout(state) {
      state.name = '';
      state.loggedIn = false;
    },
  },
});

// After (Zustand)
interface UserStore {
  name: string;
  loggedIn: boolean;
  login: (name: string) => void;
  logout: () => void;
}

const useUserStore = create<UserStore>((set) => ({
  name: '',
  loggedIn: false,
  login: (name) => set({ name, loggedIn: true }),
  logout: () => set({ name: '', loggedIn: false }),
}));

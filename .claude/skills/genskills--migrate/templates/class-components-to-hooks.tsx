// State
// Before:
class Foo extends Component {
  state = { count: 0 };
  increment = () => this.setState(prev => ({ count: prev.count + 1 }));
}
// After:
function Foo() {
  const [count, setCount] = useState(0);
  const increment = useCallback(() => setCount(prev => prev + 1), []);
}

// Lifecycle
// componentDidMount → useEffect(..., [])
// componentDidUpdate → useEffect(..., [deps])
// componentWillUnmount → useEffect(() => { return () => cleanup(); }, [])
// getDerivedStateFromProps → compute during render or useMemo
// shouldComponentUpdate → React.memo() wrapper
// componentDidCatch → no hook equivalent; keep as class ErrorBoundary

// Refs
// this.myRef = createRef() → const myRef = useRef(null)

// Context
// static contextType = MyContext → const value = useContext(MyContext)

// Instance variables (not triggering re-render)
// this.intervalId = null → const intervalId = useRef(null)

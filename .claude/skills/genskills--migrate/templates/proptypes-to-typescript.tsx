// Before
import PropTypes from 'prop-types';
function Button({ label, onClick, disabled }) {
  return <button onClick={onClick} disabled={disabled}>{label}</button>;
}
Button.propTypes = {
  label: PropTypes.string.isRequired,
  onClick: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
};
Button.defaultProps = {
  disabled: false,
};

// After
interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}
function Button({ label, onClick, disabled = false }: ButtonProps) {
  return <button onClick={onClick} disabled={disabled}>{label}</button>;
}

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseDisplay } from '../query/apis'; // นำเข้าฟังก์ชันที่สร้างไว้

function PausePositionBtn() {
  const queryClient = useQueryClient();
  const pauseMutation = useMutation({
    mutationFn: pauseDisplay, // ฟังก์ชันเรียกใช้ API
    onSuccess: () => {
      console.log('Display successfully paused.');
      queryClient.invalidateQueries({ queryKey: ['pausePositionSync'] });
      
      alert('Completed toggle position sync!');
    },
    
    onError: (error) => {
      if (error instanceof Error) {
        console.error('Error pausing display:', error.message);
        alert(`Error: ${error.message}`);
      } else {
        console.error('Error pausing display:', error);
        alert(`Error: ${String(error)}`);
      }
    },
  });

  const handlePause = () => {
    pauseMutation.mutate(); 
  };

  return (
    <div>
      <h3>Control position sync toggle</h3>
      <button 
        onClick={handlePause} 
        disabled={pauseMutation.isPending}
      >
        {pauseMutation.isPending ? 'Pausing...' : 'Toggling Position Sync'}
      </button>
      
      {pauseMutation.isError && 
        <p style={{ color: 'red' }}>
          Error: {pauseMutation.error instanceof Error ? pauseMutation.error.message : String(pauseMutation.error)}
        </p>
      }
    </div>
  );
}

export default PausePositionBtn;
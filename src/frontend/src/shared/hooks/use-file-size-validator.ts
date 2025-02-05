import { INVALID_FILE_SIZE_ALERT } from "@/constants/alerts_constants";
import { useUtilityStore } from "@/stores/utilityStore";

const useFileSizeValidator = () => {
  const maxFileSizeUpload = useUtilityStore((state) => state.maxFileSizeUpload);

  const validateFileSize = (file) => {
    if (file.size > maxFileSizeUpload) {
      throw new Error(INVALID_FILE_SIZE_ALERT(maxFileSizeUpload / 1024 / 1024));
    }
    return true;
  };

  return { validateFileSize };
};

export default useFileSizeValidator;
